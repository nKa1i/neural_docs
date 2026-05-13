import pytest
from app.utils.project_name import extract_project_name


def test_uses_llm_project_name_when_present():
    result = {"document_extended": {"project_name": "SwiftPay", "project_overview": "Long sentence here."}}
    assert extract_project_name(result) == "SwiftPay"


def test_falls_back_to_first_sentence_when_no_llm_name():
    result = {"document_extended": {"project_name": "", "project_overview": "Платформа для генерации. Второе предложение."}}
    assert extract_project_name(result) == "Платформа для генерации"


def test_falls_back_to_date_when_both_empty():
    result = {"document_extended": {"project_name": "", "project_overview": ""}}
    name = extract_project_name(result)
    assert name.startswith("Analysis ")


def test_truncates_long_llm_name():
    long_name = "A" * 60
    result = {"document_extended": {"project_name": long_name}}
    assert len(extract_project_name(result)) == 50


def test_reads_from_document_when_no_document_extended():
    result = {"document": {"project_name": "DataVault"}}
    assert extract_project_name(result) == "DataVault"


def test_handles_overview_as_dict():
    result = {"document_extended": {"project_name": "", "project_overview": {"text": "Dict overview sentence. More."}}}
    assert extract_project_name(result) == "Dict overview sentence"


def test_whitespace_only_llm_name_falls_through_to_overview():
    result = {"document_extended": {"project_name": "   ", "project_overview": "Real overview sentence. More."}}
    assert extract_project_name(result) == "Real overview sentence"
