from nose.tools import set_trace
from circulation_exceptions import *
import datetime

from core.model import (
    get_one,
    DataSource,
    Loan,
    Hold,
)

class FulfillmentInfo(object):

    """A record of an attempt to fulfil a book."""

    def __init__(self, content_link, content_type, content,
                 content_expires):
        self.content_link = content_link
        self.content_type = content_type
        self.content = content
        self.content_expires = content_expires
    
    def __repr__(self):
        if self.content:
            blength = len(self.content)
        else:
            blength = 0
        return "<FulfillmentInfo: content_link: %r, content_type: %r, content: %d bytes, expires: %r>" % (
            self.content_link, self.content_type, blength, self.content_expires)

class CirculationAPI(object):
    """Implement basic circulation logic and abstract away the details
    between different circulation APIs.
    """

    def __init__(self, _db, overdrive, threem):
        self._db = _db
        self.overdrive = overdrive
        self.threem = threem
        self.apis = [overdrive, threem]

    def api_for_license_pool(self, licensepool):
        """Find the API to use for the given license pool."""
        if licensepool.data_source.name==DataSource.OVERDRIVE:
            api = self.overdrive
            possible_formats = ["ebook-epub-adobe", "ebook-epub-open"]
        else:
            api = self.threem
            possible_formats = [None]

        return api, possible_formats

    def borrow(self, patron, pin, licensepool, hold_notification_email):
        """Either borrow a book or put it on hold. If the book is borrowed,
        also fulfill the loan.
        
        :return: A 3-tuple (borrow, hold, fulfillment). Either
        `borrow` or `hold` must be None, but not both. If `borrow` is
        present, `fulfillment` must be a `FulfillmentInfo` object.
        """
        loan = get_one(
            self._db, Loan, patron=patron, license_pool=licensepool,
            on_multiple='interchangeable'
        )
        hold = get_one(
            self._db, Hold, patron=patron, license_pool=licensepool,
            on_multiple='interchangeable'
        )

        now = datetime.datetime.utcnow()
        if loan and loan.end < now:
            # We already have an active loan. Just return it and be
            # done.
            return loan, None, None
    
        fallback_to_hold = False
        content_link = content_expires = None
        if licensepool.open_access:
            # We can handle open-access content ourselves.
            return self.borrow_open_access(patron, licensepool)

        # We need to go to an API to carry out the loan.
        api, possible_formats = self.api_for_license_pool(licensepool)

        # First, try to check out the book.
        format_to_use = possible_formats[0]
        fulfillment = None
        try:
            fulfillment = api.checkout(
                 patron, pin, licensepool,
                 format_type=format_to_use)
        except NoAvailableCopies:
            # That's fine, we'll just place a hold.
            pass
        set_trace()

        if fulfillment:
            # We successfuly secured a loan.  Now create it in our
            # database.
            loan, ignore = licensepool.loan_to(
                patron, end=fulfillment.content_expires)
            if hold:
                # The book was on hold, and now it's checked out.
                # Delete the hold in-database.
                Conf.db.delete(existing_hold)
                hold = None
        else:
            # Checking out a book didn't work, so let's try putting
            # the book on hold.
            start_date, end_date, hold_position = api.place_hold(
                patron, pin, licensepool, hold_notification_email)
            start_date = start_date or now
            hold, ignore = licensepool.on_hold_to(
                patron, start_date, end_date, hold_position)
            if loan:
                # No reason this should happen, but we can't have
                # loan and hold simultaneously.
                Conf.db.delete(loan)
            loan = None
        return loan, hold, fulfillment

    def borrow_open_access(self, patron, licensepool):
        """Give this patron a permanent loan for an open-access work.
        """
        best_pool, best_link = pool.best_license_link
        if not best_link:
            raise NoOpenAccessDownload()
        loan, ignore = pool.loan_to(patron, end=None)
        return loan, None, self.fulfill_open_access()

    def fulfill(self, patron, pin, licensepool):
        """Fulfil a book that a patron has checked out.

        :return: A FulfillmentInfo object.
        """

        # The patron must have a loan for this book. We'll try
        # fulfilling it even if the loan has expired--they may have
        # renewed it out-of-band.
        loan = get_one(Conf.db, Loan, patron=patron, license_pool=pool)
        if not loan:
            raise NoActiveLoan()

        fulfillment = None
        if licensepool.open_access:
            fulfillment = self.fulfill_open_access(licensepool)
        else:
            api, possible_formats = self.api_for_license_pool(licensepool)
            for f in possible_formats:
                fulfillment = api.fulfill(
                    patron, pin, pool.identifier, f)
                if fulfillment.content_link or fulfillment.content:
                    break
            else:
                raise NoAcceptableFormat()
            fulfillment = FulfillmentInfo(
                content_link, media_type, content, content_expires)
        return fulfillment

    def fulfill_open_access(self, licensepool):
        best_pool, best_link = pool.best_license_link
        if not best_link:
            raise NoOpenAccessDownload()

        r = best_link.representation
        if r.url:
            content_link = r.url

        media_type = best_link.representation.media_type
        return FulfillmentInfo(best_link, media_type, None, None)

    def revoke_loan(self, patron, pin, licensepool):
        """Revoke a patron's loan for a book."""
        api, possible_formats = self.api_for_license_pool(licensepool)
        try:
            api.checkin(patron, pin, licensepool)
        except NotCheckedOut, e:
            # The book wasn't checked out in the first
            # place. Everything's fine.
            pass
        # Any other CannotReturn exception will be propagated upwards.
        return True

    def release_hold(self, patron, pin, licensepool):
        """Remove a patron's hold on a book."""
        api, possible_formats = self.api_for_license_pool(licensepool)
        try:
            api.release_hold(patron, pin, licensepool)
        except NotOnHold, e:
            # The book wasn't on hold in the first place. Everything's
            # fine.
            pass
        # Any other CannotReleaseHold exception will be propagated
        # upwards.
        return True
