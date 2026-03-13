"""Small compatibility facade used by tests that call `.clear()`."""

from collections.abc import Iterable


class TableResetView:
    def __init__(self, repository, *table_names: str) -> None:
        self.repository = repository
        self.table_names: Iterable[str] = table_names

    def clear(self) -> None:
        self.repository.reset_tables(self.table_names)
