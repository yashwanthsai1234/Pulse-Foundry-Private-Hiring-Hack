"""Live panel P4: a real state license list (WA DOH) is a license file — first/last name columns,
state-style numbers (RN.RN.00094584), types like 'Registered Nurse License'."""
from pathlib import Path

from sot.parsers.csv_parser import CsvParser
from sot.core.registry import ExtractContext
from sot.core.models import FileRef
from sot.semantic.classify import classify
from sot.semantic.profile import profile_table
from sot.semantic.validators import build_validators
from datetime import datetime

WA = Path(__file__).parent / "fixtures" / "realworld" / "wa_health_credentials_sample.csv"


def test_state_license_numbers_and_types_validate(pack):
    v = build_validators(pack)
    assert all(v["credential.number"](x) for x in ["RN.RN.00094584", "RN.RN.61687583.MSL", "RN-551203", "CNA771045"])
    assert not v["credential.number"]("P-3001") and not v["credential.number"]("hello")
    assert v["credential.type"]("Registered Nurse License") and v["credential.type"]("Licensed Practical Nurse License")


def test_real_wa_license_list_routes_to_agent_and_agent_license_map_validates(pack, settings):
    data = WA.read_bytes()
    parser = CsvParser()
    f = FileRef(file_id="w" * 64, file_name=WA.name, path=str(WA), size=len(data), received_at=datetime.now())
    (t,) = parser.extract(f, ExtractContext(settings, pack, "r", parser.sniff(data[:65536], WA).details))
    profiles = profile_table(t, build_validators(pack))
    auto = classify(t, profiles, pack, settings)
    # 6 of 12 columns are unrelated to our model -> not auto-mapped; the table goes to an agent (never silently wrong)
    assert auto.template_id in (None, "license")
    agent_map = {"credentialnumber": "credential.number", "lastname": "person.family_name",
                 "firstname": "person.given_name", "credentialtype": "credential.type",
                 "expirationdate": "credential.expires_on"}
    m = classify(t, profiles, pack, settings, forced=agent_map)  # what the agent proposes must now validate as a license
    assert m.template_id == "license" and m.missing_required == [] and m.confidence >= settings["map.auto_min"]
