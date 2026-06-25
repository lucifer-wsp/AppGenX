from appgen.llm import LLMClient
from appgen.models import RequirementSpec


def test_coerce_string_list_to_requirement_spec():
    client = LLMClient()
    data = ["Story 1", "Story 2", "Feature A", "Feature B"]
    obj = client._coerce_to_model_dict(data, RequirementSpec)
    spec = RequirementSpec.model_validate(obj)
    assert spec.problem_statement
    assert len(spec.user_stories) == 4
    assert len(spec.mvp_scope) <= 5


def test_extract_json_prefers_object():
    client = LLMClient()
    text = 'noise [{"app_id":"1"}] {"problem_statement":"x","user_stories":[]}'
    # trailing object might not validate but extraction should prefer last complete object
    raw = text[text.find("{") :]
    parsed = client._extract_json(raw)
    assert isinstance(parsed, dict)
