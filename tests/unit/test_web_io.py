"""WebIO answers the backend's questions from the UI, in a worker thread (blocking) and in the agent's event loop
(awaitable), and a stop behaves like Ctrl+C at a prompt (D-089)."""

import asyncio
import threading
import time

from credagent.web.webio import WebIO


def answer_soon(io, kind, value, delay=0.1):
    def go():
        for _ in range(100):
            if io.snapshot() and io.snapshot()[0] == kind:
                time.sleep(delay)
                io.answer(kind, value)
                return
            time.sleep(0.02)
    threading.Thread(target=go, daemon=True).start()


def test_choose_blocks_in_a_plain_thread_until_the_ui_answers():
    io = WebIO()
    answer_soon(io, "choose", "Option B")
    assert io.choose("Which?", ["Option A", "Option B"]) == "Option B"
    assert io.snapshot() is None


def test_in_an_event_loop_the_same_calls_are_awaitable():
    io = WebIO()

    async def go():
        answer_soon(io, "enter", True)
        first = io.wait_enter("Press Enter")
        assert asyncio.iscoroutine(first)
        assert await first is True
        answer_soon(io, "choose", "Yes")
        return await io.choose("Sure?", ["Yes", "No"])
    assert asyncio.run(go()) == "Yes"


def test_stop_is_like_ctrl_c_and_later_questions_get_no_answer():
    io = WebIO()

    async def go():
        t = asyncio.ensure_future(io.wait_enter("Press Enter"))
        await asyncio.sleep(0.1)
        assert io.stop() is True
        assert await t is False
        assert await io.choose("again?", ["a", "b"]) is None  # already stopped: no waiting, no answer
    asyncio.run(go())


def test_answers_for_a_question_that_is_not_open_are_refused():
    io = WebIO()
    assert io.answer("enter", True) is False
    answer_soon(io, "consent", "my test account")
    assert io.wait_consent() == "my test account"
    assert io.answer("consent", "again") is False
