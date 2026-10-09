"""Read one selected external PDF behind the Application-owned boundary."""

import os
import stat
from pathlib import Path

from lexlocal.application.ports.document_workflow import (
    SelectedPdfReader,
    SelectedPdfReadError,
    SelectedPdfReference,
    SelectedPdfSource,
)


class LocalSelectedPdfReader:
    """Read exact bytes from one explicitly selected regular local file."""

    def read(self, selected: SelectedPdfReference) -> SelectedPdfSource:
        """Return exact bytes and basename while sanitizing physical-path failures."""

        if not isinstance(selected, SelectedPdfReference):
            raise SelectedPdfReadError("selected PDF reference is invalid")
        try:
            path = Path(selected.value)
            with path.open("rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise SelectedPdfReadError("selected PDF is not a regular file")
                source = stream.read()
            return SelectedPdfSource(source=source, logical_filename=path.name)
        except SelectedPdfReadError:
            raise
        except Exception:
            raise SelectedPdfReadError("selected PDF could not be read") from None


_READER_CONFORMANCE: SelectedPdfReader = LocalSelectedPdfReader()
