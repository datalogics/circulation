from nose.tools import (
    assert_raises_regexp,
    set_trace,
    eq_,
)
import datetime
import os
import pkgutil
from api.threem import (
    CirculationParser,
    EventParser,
    ErrorParser,
    #EnkiEventMonitor,
)
from core.model import (
    CirculationEvent,
    Contributor,
    DataSource,
    LicensePool,
    Resource,
    Hyperlink,
    Identifier,
    Edition,
    Timestamp,
    Subject,
    Measurement,
    Work,
)
from . import DatabaseTest
from api.circulation_exceptions import *
from api.enki import (
    EnkiAPI,
    MockEnkiAPI,
    EnkiBibliographicCoverageProvider,
)
from scripts import RunCoverageProviderScript
from core.util.http import BadResponseException
from core.testing import MockRequestsResponse

class BaseEnkiTest(object):

    base_path = os.path.split(__file__)[0]
    resource_path = os.path.join(base_path, "files", "enki")

    @classmethod
    def get_data(cls, filename):
        path = os.path.join(cls.resource_path, filename)
        return open(path).read()


class TestEnkiAPI(DatabaseTest, BaseEnkiTest):

    def setup(self):
        super(TestEnkiAPI, self).setup()
        self.api = MockEnkiAPI(self._db)

    def test_create_identifier_strings(self):
        identifier = self._identifier()
        values = EnkiAPI.create_identifier_strings(["foo", identifier])
        eq_(["foo", identifier.identifier], values)



class TestBibliographicCoverageProvider(TestEnkiAPI):

    """Test the code that looks up bibliographic information from Enki."""

    def test_script_instantiation(self):
        """Test that RunCoverageProviderScript can instantiate
        the coverage provider.
        """
        script = RunCoverageProviderScript(
            EnkiBibliographicCoverageProvider, self._db, [],
            enki_api=self.api
        )
        assert isinstance(script.provider,
                          EnkiBibliographicCoverageProvider)
        eq_(script.provider.api, self.api)

    def test_process_item_creates_presentation_ready_work(self):
        """Test the normal workflow where we ask Enki for data,
        Enki provides it, and we create a presentation-ready work.
        """

        data = self.get_data("item_metadata_single.json")
        self.api.queue_response(200, content=data)

        identifier = self._identifier(identifier_type=Identifier.ENKI_ID)
        identifier.identifier = 'econtentRecord1'

        # This book has no LicensePool.
        eq_(None, identifier.licensed_through)

        # Run it through the ThreeMBibliographicCoverageProvider
        provider = EnkiBibliographicCoverageProvider(
            self._db, enki_api=self.api
        )
        [result] = provider.process_batch([identifier])
        eq_(identifier, result)

        # A LicensePool was created, not because we know anything
        # about how we've licensed this book, but to have a place to
        # store the information about what formats the book is
        # available in.
        pool = identifier.licensed_through
        eq_(1, pool.licenses_owned)
        # A Work was created and made presentation ready.
        eq_("1984", pool.work.title)
        eq_(True, pool.work.presentation_ready)

class TestErrorParser(object):

    # Some sample error documents.

    NOT_LOANABLE = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>the patron document status was CAN_HOLD and not one of CAN_LOAN,RESERVATION</Message></Error>'

    ALREADY_ON_LOAN = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>the patron document status was LOAN and not one of CAN_LOAN,RESERVATION</Message></Error>'

    TRIED_TO_RETURN_UNLOANED_BOOK = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>The patron has no eBooks checked out</Message></Error>'

    TRIED_TO_HOLD_LOANABLE_BOOK = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>the patron document status was CAN_LOAN and not one of CAN_HOLD</Message></Error>'

    TRIED_TO_HOLD_BOOK_ON_LOAN = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>the patron document status was LOAN and not one of CAN_HOLD</Message></Error>'

    ALREADY_ON_HOLD = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>the patron document status was HOLD and not one of CAN_HOLD</Message></Error>'

    TRIED_TO_CANCEL_NONEXISTENT_HOLD = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>The patron does not have the book on hold</Message></Error>'

    TOO_MANY_LOANS = '<Error xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><Code>Gen-001</Code><Message>Patron cannot loan more than 12 documents</Message></Error>'

    def test_exception(self):
        parser = ErrorParser()

        error = parser.process_all(self.NOT_LOANABLE)
        assert isinstance(error, NoAvailableCopies)

        error = parser.process_all(self.ALREADY_ON_LOAN)
        assert isinstance(error, AlreadyCheckedOut)

        error = parser.process_all(self.ALREADY_ON_HOLD)
        assert isinstance(error, AlreadyOnHold)

        error = parser.process_all(self.TOO_MANY_LOANS)
        assert isinstance(error, PatronLoanLimitReached)

        error = parser.process_all(self.TRIED_TO_CANCEL_NONEXISTENT_HOLD)
        assert isinstance(error, NotOnHold)

        error = parser.process_all(self.TRIED_TO_RETURN_UNLOANED_BOOK)
        assert isinstance(error, NotCheckedOut)

        error = parser.process_all(self.TRIED_TO_HOLD_LOANABLE_BOOK)
        assert isinstance(error, CurrentlyAvailable)

        # This is such a weird case we don't have a special
        # exception for it.
        error = parser.process_all(self.TRIED_TO_HOLD_BOOK_ON_LOAN)
        assert isinstance(error, CannotHold)
