"""Writes one call's answers into its row of the sheet as they come in.

The sheet fills in while the person is still talking, which is the point of a demo. Writes run in
the background, one at a time and in order, so the conversation never waits on Google; a failed
write is logged and the call carries on. The final write, when the call ends, holds every answer,
the status and the transcript, so an update lost in between costs nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping

from agent.sheets import ContactSheet

logger = logging.getLogger("agent.survey.recorder")

TEST_CALL = "(test call)"  # the phone column of a row added for a call that didn't come from the sheet
FINAL_WRITE_SECONDS = 20.0


class SheetRecorder:
    def __init__(self, sheet: ContactSheet | None, row: int | None, *, phone: str | None) -> None:
        """`row` None: a test call with no row of its own, which gets one on its first write."""
        self._sheet = sheet
        self._row = row
        self._phone = phone
        self._pending: dict[str, str] = {}
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._closing = False

    @property
    def enabled(self) -> bool:
        return self._sheet is not None

    @property
    def row(self) -> int | None:
        return self._row

    def write(self, values: Mapping[str, str]) -> None:
        """Queue cells for this call's row. Writes are merged: the latest value of each cell wins."""
        if self._sheet is None or self._closing:
            return
        self._pending.update(values)
        self._wake.set()
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="sheet_recorder")

    async def close(self, final: Mapping[str, str]) -> None:
        """The last write, with everything; waits (a while) for it and anything queued before it."""
        if self._sheet is None:
            return
        self.write(final)
        self._closing = True
        self._wake.set()
        if self._task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._task), FINAL_WRITE_SECONDS)
        except TimeoutError:
            logger.warning(
                "the sheet is still being written %.0f s after the call ended", FINAL_WRITE_SECONDS
            )

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            if values := self._pending:
                self._pending = {}
                if not await self._flush(values):
                    # Keep what didn't go through; newer values for the same cells still win.
                    self._pending = {**values, **self._pending}
                    if self._closing:
                        return  # the final write failed too: logged, nothing more to do
            if self._closing and not self._pending:
                return

    async def _flush(self, values: dict[str, str]) -> bool:
        assert self._sheet is not None
        try:
            if self._row is None:
                self._row = await self._sheet.append({"phone": self._phone or TEST_CALL, **values})
                logger.info("test call recorded in row %d of %s", self._row, self._sheet.label)
            else:
                await self._sheet.update(self._row, values)
        except Exception as e:  # never let the sheet break a call
            logger.warning("couldn't write to %s: %s", self._sheet.label, e)
            return False
        return True

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
