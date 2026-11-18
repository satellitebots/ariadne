"""ACL: load and manage access-control lists from a YAML config."""

import json
from pathlib import Path
from typing import Optional

import yaml


class ACL:
    """Load ACL rules from a YAML file and filter documents by principal."""

    def __init__(self, config_path: str | Path = "acl.yaml"):
        self.config_path = Path(config_path)
        self.rules: dict[str, list[str]] = {}  # doc_prefix -> [principals]
        self.principals: dict[str, set[str]] = {}  # user -> {groups}
        self.load()

    def load(self):
        """Load ACL configuration from the YAML file."""
        if not self.config_path.exists():
            return
        with open(self.config_path) as f:
            data = yaml.safe_load(f) or {}
        self.rules = data.get("rules", {})
        self.principals = data.get("principals", {})

    def get_principals_for_doc(self, source_path: str) -> list[str]:
        """Return the list of principals that can access a document.

        Matches by longest prefix of source_path against rules.
        """
        best_prefix = None
        best_principals = []
        for prefix, principals in self.rules.items():
            if source_path.startswith(prefix):
                if best_prefix is None or len(prefix) > len(best_prefix):
                    best_prefix = prefix
                    best_principals = principals
        return best_principals

    def resolve_user_principals(self, user: str) -> set[str]:
        """Return the set of all principals for a user (user + groups)."""
        result = {user}
        groups = self.principals.get(user, [])
        result.update(groups)
        return result
