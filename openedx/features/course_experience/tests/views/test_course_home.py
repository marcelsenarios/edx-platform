# coding=utf-8
"""
Tests for the course home page.
"""
from datetime import datetime, timedelta
import ddt
import mock
from pytz import UTC
from waffle.testutils import override_flag

from courseware.tests.factories import StaffFactory
from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import QueryDict
from django.utils.http import urlquote_plus
from openedx.core.djangoapps.waffle_utils.testutils import WAFFLE_TABLES, override_waffle_flag
from openedx.features.course_experience import SHOW_REVIEWS_TOOL_FLAG, UNIFIED_COURSE_TAB_FLAG
from student.models import CourseEnrollment
from student.tests.factories import UserFactory
from util.date_utils import strftime_localized
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.tests.django_utils import CourseUserType, SharedModuleStoreTestCase
from xmodule.modulestore.tests.factories import CourseFactory, ItemFactory, check_mongo_calls

from ... import COURSE_PRE_START_ACCESS_FLAG
from .helpers import add_course_mode
from .test_course_updates import create_course_update

TEST_PASSWORD = 'test'
TEST_CHAPTER_NAME = 'Test Chapter'
TEST_WELCOME_MESSAGE = '<h2>Welcome!</h2>'
TEST_UPDATE_MESSAGE = '<h2>Test Update!</h2>'
TEST_COURSE_UPDATES_TOOL = '/course/updates">'
TEST_COURSE_HOME_MESSAGE = 'course-message'
TEST_COURSE_HOME_MESSAGE_ANONYMOUS = '/login'
TEST_COURSE_HOME_MESSAGE_UNENROLLED = 'Enroll now'
TEST_COURSE_HOME_MESSAGE_PRE_START = 'Course starts in'

QUERY_COUNT_TABLE_BLACKLIST = WAFFLE_TABLES


def course_home_url(course):
    """
    Returns the URL for the course's home page.

    Arguments:
        course (CourseDescriptor): The course being tested.
    """
    return course_home_url_from_string(unicode(course.id))


def course_home_url_from_string(course_key_string):
    """
    Returns the URL for the course's home page.

    Arguments:
        course_key_string (String): The course key as string.
    """
    return reverse(
        'openedx.course_experience.course_home',
        kwargs={
            'course_id': course_key_string,
        }
    )


class CourseHomePageTestCase(SharedModuleStoreTestCase):
    """
    Base class for testing the course home page.
    """
    @classmethod
    def setUpClass(cls):
        """
        Set up a course to be used for testing.
        """
        # setUpClassAndTestData() already calls setUpClass on SharedModuleStoreTestCase
        # pylint: disable=super-method-not-called
        with super(CourseHomePageTestCase, cls).setUpClassAndTestData():
            with cls.store.default_store(ModuleStoreEnum.Type.split):
                cls.course = CourseFactory.create(
                    org='edX',
                    number='test',
                    display_name='Test Course',
                    start=datetime.now(UTC) - timedelta(days=30),
                )
                with cls.store.bulk_operations(cls.course.id):
                    chapter = ItemFactory.create(
                        category='chapter',
                        parent_location=cls.course.location,
                        display_name=TEST_CHAPTER_NAME,
                    )
                    section = ItemFactory.create(category='sequential', parent_location=chapter.location)
                    section2 = ItemFactory.create(category='sequential', parent_location=chapter.location)
                    ItemFactory.create(category='vertical', parent_location=section.location)
                    ItemFactory.create(category='vertical', parent_location=section2.location)

    @classmethod
    def setUpTestData(cls):
        """Set up and enroll our fake user in the course."""
        cls.staff_user = StaffFactory(course_key=cls.course.id, password=TEST_PASSWORD)
        cls.user = UserFactory(password=TEST_PASSWORD)
        CourseEnrollment.enroll(cls.user, cls.course.id)

    def create_future_course(self, specific_date=None):
        """
        Creates and returns a course in the future.
        """
        return CourseFactory.create(
            display_name='Test Future Course',
            start=specific_date if specific_date else datetime.now(UTC) + timedelta(days=30),
        )


class TestCourseHomePage(CourseHomePageTestCase):
    def setUp(self):
        """
        Set up for the tests.
        """
        super(TestCourseHomePage, self).setUp()
        self.client.login(username=self.user.username, password=TEST_PASSWORD)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    def test_welcome_message_when_unified(self):
        # Create a welcome message
        create_course_update(self.course, self.user, TEST_WELCOME_MESSAGE)

        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertContains(response, TEST_WELCOME_MESSAGE, status_code=200)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=False)
    def test_welcome_message_when_not_unified(self):
        # Create a welcome message
        create_course_update(self.course, self.user, TEST_WELCOME_MESSAGE)

        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertNotContains(response, TEST_WELCOME_MESSAGE, status_code=200)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    def test_updates_tool_visibility(self):
        """
        Verify that the updates course tool is visible only when the course
        has one or more updates.
        """
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertNotContains(response, TEST_COURSE_UPDATES_TOOL, status_code=200)

        create_course_update(self.course, self.user, TEST_UPDATE_MESSAGE)
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertContains(response, TEST_COURSE_UPDATES_TOOL, status_code=200)

    def test_queries(self):
        """
        Verify that the view's query count doesn't regress.
        """
        # Pre-fetch the view to populate any caches
        course_home_url(self.course)

        # Fetch the view and verify the query counts
        with self.assertNumQueries(41, table_blacklist=QUERY_COUNT_TABLE_BLACKLIST):
            with check_mongo_calls(4):
                url = course_home_url(self.course)
                self.client.get(url)

    @mock.patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_start_date_handling(self):
        """
        Verify that the course home page handles start dates correctly.
        """
        # The course home page should 404 for a course starting in the future
        future_course = self.create_future_course(datetime(2030, 1, 1, tzinfo=UTC))
        url = course_home_url(future_course)
        response = self.client.get(url)
        self.assertRedirects(response, '/dashboard?notlive=Jan+01%2C+2030')

        # With the Waffle flag enabled, the course should be visible
        with override_flag(COURSE_PRE_START_ACCESS_FLAG.namespaced_flag_name, True):
            url = course_home_url(future_course)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)


@ddt.ddt
class TestCourseHomePageAccess(CourseHomePageTestCase):
    """
    Test access to the course home page.
    """

    def setUp(self):
        super(TestCourseHomePageAccess, self).setUp()

        # Make this a verified course so that an upgrade message might be shown
        add_course_mode(self.course, upgrade_deadline_expired=False)

        # Add a welcome message
        create_course_update(self.course, self.staff_user, TEST_WELCOME_MESSAGE)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    @override_waffle_flag(SHOW_REVIEWS_TOOL_FLAG, active=True)
    @ddt.data(
        [CourseUserType.ANONYMOUS, 'To see course content'],
        [CourseUserType.ENROLLED, None],
        [CourseUserType.UNENROLLED, 'You must be enrolled in the course to see course content.'],
        [CourseUserType.UNENROLLED_STAFF, None],
    )
    @ddt.unpack
    def test_home_page(self, user_type, expected_message):
        self.user = self.create_user_for_course(self.course, user_type)

        # Render the course home page
        url = course_home_url(self.course)
        response = self.client.get(url)

        # Verify that the course tools and dates are always shown
        self.assertContains(response, 'Course Tools')
        self.assertContains(response, 'Today is')

        # Verify that the outline, start button, course sock, and welcome message
        # are only shown to enrolled users.
        is_enrolled = user_type is CourseUserType.ENROLLED
        is_unenrolled_staff = user_type is CourseUserType.UNENROLLED_STAFF
        expected_count = 1 if (is_enrolled or is_unenrolled_staff) else 0
        self.assertContains(response, TEST_CHAPTER_NAME, count=expected_count)
        self.assertContains(response, 'Start Course', count=expected_count)
        self.assertContains(response, 'Learn About Verified Certificate', count=expected_count)
        self.assertContains(response, TEST_WELCOME_MESSAGE, count=expected_count)

        # Verify that the expected message is shown to the user
        self.assertContains(response, '<div class="user-messages">', count=1 if expected_message else 0)
        if expected_message:
            self.assertContains(response, expected_message)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=False)
    @override_waffle_flag(SHOW_REVIEWS_TOOL_FLAG, active=True)
    @ddt.data(
        [CourseUserType.ANONYMOUS, 'To see course content'],
        [CourseUserType.ENROLLED, None],
        [CourseUserType.UNENROLLED, 'You must be enrolled in the course to see course content.'],
        [CourseUserType.UNENROLLED_STAFF, None],
    )
    @ddt.unpack
    def test_home_page_not_unified(self, user_type, expected_message):
        """
        Verifies the course home tab when not unified.
        """
        self.user = self.create_user_for_course(self.course, user_type)

        # Render the course home page
        url = course_home_url(self.course)
        response = self.client.get(url)

        # Verify that the course tools and dates are always shown
        self.assertContains(response, 'Course Tools')
        self.assertContains(response, 'Today is')

        # Verify that welcome messages are never shown
        self.assertNotContains(response, TEST_WELCOME_MESSAGE)

        # Verify that the outline, start button, course sock, and welcome message
        # are only shown to enrolled users.
        is_enrolled = user_type is CourseUserType.ENROLLED
        is_unenrolled_staff = user_type is CourseUserType.UNENROLLED_STAFF
        expected_count = 1 if (is_enrolled or is_unenrolled_staff) else 0
        self.assertContains(response, TEST_CHAPTER_NAME, count=expected_count)
        self.assertContains(response, 'Start Course', count=expected_count)
        self.assertContains(response, 'Learn About Verified Certificate', count=expected_count)

        # Verify that the expected message is shown to the user
        self.assertContains(response, '<div class="user-messages">', count=1 if expected_message else 0)
        if expected_message:
            self.assertContains(response, expected_message)

    def test_sign_in_button(self):
        """
        Verify that the sign in button will return to this page.
        """
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertContains(response, '/login?next={url}'.format(url=urlquote_plus(url)))

    @mock.patch.dict(settings.FEATURES, {'DISABLE_START_DATES': False})
    def test_non_live_course(self):
        """
        Ensure that a user accessing a non-live course sees a redirect to
        the student dashboard, not a 404.
        """
        future_course = self.create_future_course()
        self.user = self.create_user_for_course(future_course, CourseUserType.ENROLLED)

        url = course_home_url(future_course)
        response = self.client.get(url)
        start_date = strftime_localized(future_course.start, 'SHORT_DATE')
        expected_params = QueryDict(mutable=True)
        expected_params['notlive'] = start_date
        expected_url = '{url}?{params}'.format(
            url=reverse('dashboard'),
            params=expected_params.urlencode()
        )
        self.assertRedirects(response, expected_url)

    @mock.patch.dict(settings.FEATURES, {'DISABLE_START_DATES': False})
    @mock.patch("util.date_utils.strftime_localized")
    def test_non_live_course_other_language(self, mock_strftime_localized):
        """
        Ensure that a user accessing a non-live course sees a redirect to
        the student dashboard, not a 404, even if the localized date is unicode
        """
        future_course = self.create_future_course()
        self.user = self.create_user_for_course(future_course, CourseUserType.ENROLLED)

        fake_unicode_start_time = u"üñîçø∂é_ßtå®t_tîµé"
        mock_strftime_localized.return_value = fake_unicode_start_time

        url = course_home_url(future_course)
        response = self.client.get(url)
        expected_params = QueryDict(mutable=True)
        expected_params['notlive'] = fake_unicode_start_time
        expected_url = u'{url}?{params}'.format(
            url=reverse('dashboard'),
            params=expected_params.urlencode()
        )
        self.assertRedirects(response, expected_url)

    def test_nonexistent_course(self):
        """
        Ensure a non-existent course results in a 404.
        """
        self.user = self.create_user_for_course(self.course, CourseUserType.ANONYMOUS)

        url = course_home_url_from_string('not/a/course')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    @override_waffle_flag(UNIFIED_COURSE_TAB_FLAG, active=True)
    @override_waffle_flag(COURSE_PRE_START_ACCESS_FLAG, active=True)
    def test_course_messaging(self):
        """
        Ensure that the following four use cases work as expected

        1) Anonymous users are shown a course message linking them to the login page
        2) Unenrolled users are shown a course message allowing them to enroll
        3) Enrolled users who show up on the course page after the course has begun
        are not shown a course message.
        4) Enrolled users who show up on the course page before the course begins
        are shown a message explaining when the course starts as well as a call to
        action button that allows them to add a calendar event.
        """
        # Verify that anonymous users are shown a login link in the course message
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE_ANONYMOUS)

        # Verify that unenrolled users are shown an enroll call to action message
        self.user = self.create_user_for_course(self.course, CourseUserType.UNENROLLED)
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE_UNENROLLED)

        # Verify that enrolled users are not shown a message when enrolled and course has begun
        CourseEnrollment.enroll(self.user, self.course.id)
        url = course_home_url(self.course)
        response = self.client.get(url)
        self.assertNotContains(response, TEST_COURSE_HOME_MESSAGE)

        # Verify that enrolled users are shown 'days until start' message before start date
        future_course = self.create_future_course()
        CourseEnrollment.enroll(self.user, future_course.id)
        url = course_home_url(future_course)
        response = self.client.get(url)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE)
        self.assertContains(response, TEST_COURSE_HOME_MESSAGE_PRE_START)
