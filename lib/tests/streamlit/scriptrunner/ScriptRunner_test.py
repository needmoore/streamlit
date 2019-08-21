# Copyright 2019 Streamlit Inc. All rights reserved.

"""Tests ScriptRunner functionality"""

import os
import time
import unittest

from streamlit.DeltaGenerator import DeltaGenerator
from streamlit.Report import Report
from streamlit.ReportQueue import ReportQueue
from streamlit.ScriptRequestQueue import RerunData
from streamlit.ScriptRequestQueue import ScriptRequest
from streamlit.ScriptRequestQueue import ScriptRequestQueue
from streamlit.ScriptRunner import ScriptRunner
from streamlit.ScriptRunner import ScriptRunnerEvent
from streamlit.proto.Widget_pb2 import WidgetStates


def _create_widget(id, states):
    """
    Returns
    -------
    streamlit.proto.Widget_pb2.WidgetState

    """
    states.widgets.add().id = id
    return states.widgets[-1]


class ScriptRunnerTest(unittest.TestCase):
    def test_startup_shutdown(self):
        """Test that we can create and shut down a ScriptRunner."""
        scriptrunner = TestScriptRunner('good_script.py')
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [ScriptRunnerEvent.SHUTDOWN])
        self._assert_text_deltas(scriptrunner, [])

    def test_run_script(self):
        """Tests that we can run a script to completion."""
        scriptrunner = TestScriptRunner('good_script.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, ['complete!'])

    def test_compile_error(self):
        """Tests that we get an exception event when a script can't compile."""
        scriptrunner = TestScriptRunner('compile_error.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_COMPILE_ERROR,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, [])

    def test_missing_script(self):
        """Tests that we get an exception event when a script doesn't exist."""
        scriptrunner = TestScriptRunner('i_do_not_exist.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_COMPILE_ERROR,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, [])

    def test_runtime_error(self):
        """Tests that we correctly handle scripts with runtime errors."""
        scriptrunner = TestScriptRunner('runtime_error.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SHUTDOWN
        ])

        # We'll get two deltas: one for st.empty(), and one for the exception
        # that gets thrown afterwards.
        self._assert_text_deltas(scriptrunner, ['first'])
        self._assert_num_deltas(scriptrunner, 2)

    def test_stop_script(self):
        """Tests that we can stop a script while it's running."""
        scriptrunner = TestScriptRunner('infinite_loop.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()

        time.sleep(0.1)
        scriptrunner.enqueue_rerun()
        time.sleep(0.1)
        scriptrunner.enqueue_stop()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, ['loop_forever'])

    def test_shutdown(self):
        """Test that we can shutdown while a script is running."""
        scriptrunner = TestScriptRunner('infinite_loop.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()

        time.sleep(0.1)
        scriptrunner.enqueue_shutdown()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, ['loop_forever'])

    def test_widgets(self):
        """Tests that widget values behave as expected."""
        scriptrunner = TestScriptRunner('widgets_script.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.start()

        # Default widget values
        time.sleep(0.1)
        self._assert_text_deltas(
            scriptrunner,
            ['False', 'ahoy!', '0', 'False', 'loop_forever'])

        # Update widgets
        states = WidgetStates()
        _create_widget('checkbox-checkbox', states).bool_value = True
        _create_widget('text_area-text_area', states).string_value = 'matey!'
        _create_widget('radio-radio', states).int_value = 2
        _create_widget('button-button', states).trigger_value = True

        scriptrunner.enqueue_rerun(widget_state=states)
        time.sleep(0.1)
        self._assert_text_deltas(
            scriptrunner,
            ['True', 'matey!', '2', 'True', 'loop_forever'])

        # Rerun with previous values. Our button should be reset;
        # everything else should be the same.
        scriptrunner.enqueue_rerun()
        time.sleep(0.1)
        self._assert_text_deltas(
            scriptrunner,
            ['True', 'matey!', '2', 'False', 'loop_forever'])

        scriptrunner.enqueue_shutdown()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)

    def test_coalesce_rerun(self):
        """Tests that multiple pending rerun requests get coalesced."""
        scriptrunner = TestScriptRunner('good_script.py')
        scriptrunner.enqueue_rerun()
        scriptrunner.enqueue_rerun()
        scriptrunner.enqueue_rerun()
        scriptrunner.start()
        scriptrunner.join()

        self._assert_no_exceptions(scriptrunner)
        self._assert_events(scriptrunner, [
            ScriptRunnerEvent.SCRIPT_STARTED,
            ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
            ScriptRunnerEvent.SHUTDOWN
        ])
        self._assert_text_deltas(scriptrunner, ['complete!'])

    def test_multiple_scriptrunners(self):
        """Tests that multiple scriptrunners can run simultaneously."""

        # Build several runners. Each will set a different int value for
        # its radio button.
        runners = []
        for ii in range(3):
            runner = TestScriptRunner('widgets_script.py')
            runners.append(runner)

            states = WidgetStates()
            _create_widget('radio-radio', states).int_value = ii
            runner.enqueue_rerun(widget_state=states)

        # Start the runners and wait a beat.
        for runner in runners:
            runner.start()

        time.sleep(0.1)

        # Ensure that each runner's radio value is as expected.
        for ii, runner in enumerate(runners):
            self._assert_text_deltas(
                runner,
                ['False', 'ahoy!', '%s' % ii, 'False', 'loop_forever'])

            runner.enqueue_shutdown()

        time.sleep(0.1)

        # Shut 'em all down!
        for runner in runners:
            runner.join()

        for runner in runners:
            self._assert_no_exceptions(runner)
            self._assert_events(runner, [
                ScriptRunnerEvent.SCRIPT_STARTED,
                ScriptRunnerEvent.SCRIPT_STOPPED_WITH_SUCCESS,
                ScriptRunnerEvent.SHUTDOWN
            ])

    def _assert_no_exceptions(self, scriptrunner):
        """Asserts that no uncaught exceptions were thrown in the
        scriptrunner's run thread.

        Parameters
        ----------
        scriptrunner : TestScriptRunner

        """
        self.assertEqual([], scriptrunner.script_thread_exceptions)

    def _assert_events(self, scriptrunner, events):
        """Asserts the ScriptRunnerEvents emitted by a TestScriptRunner are
        what we expect.

        Parameters
        ----------
        scriptrunner : TestScriptRunner
        events : list

        """
        self.assertEqual(events, scriptrunner.events)

    def _assert_num_deltas(self, scriptrunner, num_deltas):
        """Asserts that the given number of delta ForwardMsgs were enqueued
        during script execution.

        Parameters
        ----------
        scriptrunner : TestScriptRunner
        num_deltas : int

        """
        self.assertEqual(num_deltas, len(scriptrunner.deltas()))

    def _assert_text_deltas(self, scriptrunner, text_deltas):
        """Asserts that the scriptrunner's ReportQueue contains text deltas
        with the given contents.

        Parameters
        ----------
        scriptrunner : TestScriptRunner
        text_deltas : List[str]

        """
        self.assertEqual(
            text_deltas,
            [
                delta.new_element.text.body for delta in scriptrunner.deltas()
                if delta.HasField('new_element') and
                delta.new_element.HasField('text')
            ]
        )


class TestScriptRunner(ScriptRunner):
    """Subclasses ScriptRunner to provide some testing features."""

    def __init__(self, script_name):
        """Initializes the ScriptRunner for the given script_name"""
        # DeltaGenerator deltas will be enqueued into self.report_queue.
        self.report_queue = ReportQueue()

        def enqueue_fn(msg):
            self.report_queue.enqueue(msg)
            self.maybe_handle_execution_control_request()
            return True

        self.dg = DeltaGenerator(enqueue_fn)
        self.script_request_queue = ScriptRequestQueue()

        script_path = os.path.join(
            os.path.dirname(__file__),
            'test_data',
            script_name)

        super(TestScriptRunner, self).__init__(
            report=Report(script_path, []),
            root_dg=self.dg,
            widget_states=WidgetStates(),
            request_queue=self.script_request_queue
        )

        # Accumulates uncaught exceptions thrown by our run thread.
        self.script_thread_exceptions = []

        # Accumulates all ScriptRunnerEvents emitted by us.
        self.events = []

        def record_event(event, **kwargs):
            self.events.append(event)

        self.on_event.connect(record_event, weak=False)

    @property
    def widget_states(self):
        """
        Returns
        -------
        WidgetStates
            A WidgetStates protobuf object

        """
        return self._widgets.get_state()

    def enqueue_rerun(self, argv=None, widget_state=None):
        self.script_request_queue.enqueue(
            ScriptRequest.RERUN,
            RerunData(argv=argv, widget_state=widget_state))

    def enqueue_stop(self):
        self.script_request_queue.enqueue(ScriptRequest.STOP)

    def enqueue_shutdown(self):
        self.script_request_queue.enqueue(ScriptRequest.SHUTDOWN)

    def _process_request_queue(self):
        try:
            super(TestScriptRunner, self)._process_request_queue()
        except BaseException as e:
            self.script_thread_exceptions.append(e)

    def join(self):
        """Joins the run thread, if it was started"""
        if self._script_thread is not None:
            self._script_thread.join()

    def deltas(self):
        """Returns the delta messages in our ReportQueue"""
        return [msg.delta for msg in self.report_queue._queue
                if msg.HasField('delta')]