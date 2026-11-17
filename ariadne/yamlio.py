"""YAML in and out with what Hermes's venv already has (ruamel.yaml); PyYAML if it is there instead."""
import io

try:
    from ruamel.yaml import YAML

    def safe_load(text):
        return YAML(typ="safe").load(text)

    def safe_dump(data, sort_keys=False):
        y = YAML(typ="safe")
        y.default_flow_style = False
        y.sort_base_mapping_type_on_output = sort_keys
        buf = io.StringIO()
        y.dump(data, buf)
        return buf.getvalue()
except ImportError:  # pragma: no cover
    from yaml import safe_dump, safe_load  # noqa: F401
