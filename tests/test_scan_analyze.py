from appgen.discovery import MarketScanner
from appgen.llm import LLMClient


def test_extract_json_list_from_array():
    client = LLMClient()
    raw = 'prefix [{"title": "A", "one_liner": "x"}, {"title": "B"}] suffix'
    items = client.extract_json_list(raw)
    assert len(items) == 2
    assert items[0]["title"] == "A"


def test_extract_json_list_not_confused_by_object_priority():
    """回归：数组响应不能被 _extract_json 的对象优先逻辑截断为单条。"""
    client = LLMClient()
    raw = '[{"title":"Opp1","one_liner":"a","country":"us"},{"title":"Opp2","one_liner":"b","country":"us"}]'
    items = client.extract_json_list(raw)
    assert len(items) == 2


def test_parse_opportunity_items_single_dict():
    data = {"title": "Test", "one_liner": "hello", "country": "us"}
    items = MarketScanner._parse_opportunity_items(data)
    assert len(items) == 1
