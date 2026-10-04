"""R1-10: one failing file must not abort the batch or poison a re-upload."""
from tests.review.r1_support import HR, PAY, LIC, run_pipeline
from sot.pipeline import orchestrator
from sot.config import load_settings
from sot.pipeline.orchestrator import Pipeline


def test_one_failing_file_does_not_lose_the_others_or_block_a_retry(tmp_path, monkeypatch):
    settings = load_settings(runtime=tmp_path / "rt")
    settings.agents = "off"
    src = tmp_path / "src"
    src.mkdir()
    for n, b in {"hr_roster.csv": HR, "payroll.csv": PAY, "licenses.csv": LIC}.items():
        (src / n).write_text(b)
    real = orchestrator.map_table

    def flaky(t, *a, **k):
        if t.file.file_name == "payroll.csv":
            raise RuntimeError("boom")
        return real(t, *a, **k)

    monkeypatch.setattr(orchestrator, "map_table", flaky)
    pipe = Pipeline(settings)
    try:
        pipe.ingest([src / "hr_roster.csv", src / "payroll.csv", src / "licenses.csv"], run_id="r1")
    except RuntimeError:
        pass
    # the licence file after the bad one was never read ...
    n_lic = pipe.db.query("SELECT count(*) n FROM files WHERE file_name = 'licenses.csv'")[0]["n"]
    assert n_lic == 1
    # ... and once the fault is fixed the bad file is still treated as already ingested
    monkeypatch.setattr(orchestrator, "map_table", real)
    pipe.ingest([src / "payroll.csv"], run_id="r2")
    assert pipe.db.query("SELECT count(*) n FROM source_records WHERE template_id = 'payroll'")[0]["n"] == 2
