import time


def test_health_and_config(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["device"] == "cpu"
    c = client.get("/config").json()
    assert c["watermark"]["hashing_key"] == "(hidden)"


def test_generate_and_save(client):
    r = client.post("/generate", json={"prompt": "hi", "max_new_tokens": 60, "mode": "normal", "seed": 5})
    assert r.status_code == 200
    gen = r.json()
    assert gen["mode"] == "normal" and gen["seed"] == 5 and gen["new_tokens"] == 60
    s = client.post("/generate/save", json={"generation": gen}).json()
    assert s["text_path"].endswith(".txt") and s["sidecar_path"].endswith(".json")
    bad = client.post("/generate", json={"prompt": "", "max_new_tokens": 60})
    assert bad.status_code == 422


def test_detect_logs_a_row_and_rejects_short_text(client):
    r = client.post("/detect", json={"text": "wm " * 150, "filename": "a.txt", "source": "file"})
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "LIKELY MARKTEXT" and body["run_id"] and body["log_error"] is None
    rows = client.get("/history").json()
    assert rows["total"] == 1 and rows["rows"][0]["filename"] == "a.txt"
    assert rows["kpis"]["count"] == 1 and rows["thresholds"]["detection_threshold"] == 4.0
    short = client.post("/detect", json={"text": "hi there"})
    assert short.status_code == 422


def test_history_filters_update_delete_clear(client):
    a = client.post("/detect", json={"text": "wm " * 150, "filename": "a.txt", "source": "file"}).json()["run_id"]
    b = client.post("/detect", json={"text": "nm " * 150}).json()["run_id"]
    h = client.get("/history", params={"result": ["NOT DETECTED"]}).json()
    assert h["kpis"]["count"] == 1 and h["rows"][0]["run_id"] == b
    h = client.get("/history", params={"q": "a.t"}).json()
    assert h["rows"][0]["run_id"] == a
    u = client.patch("/history/{}".format(a), json={"note": "checked"})
    assert u.status_code == 200 and u.json()["record"]["note"] == "checked"
    assert client.patch("/history/nope", json={"note": "x"}).status_code == 404
    assert client.patch("/history/{}".format(a), json={}).status_code == 422
    assert client.get("/history/{}".format(a)).json()["note"] == "checked"
    d = client.delete("/history/{}".format(a))
    assert d.status_code == 200 and client.get("/history/{}".format(a)).status_code == 404
    e = client.get("/history/export")
    assert e.status_code == 200 and "run_id" in e.text and e.headers["x-saved-path"].endswith(".csv")
    c = client.post("/history/clear").json()
    assert c["backup"] and client.get("/history").json()["total"] == 0


def test_experiment_job_lifecycle(client):
    assert client.get("/prompts").json()["count"] == 3
    r = client.post("/experiments", json={"n_prompts": 2, "lengths": [50], "runs": 1, "seed_base": 9})
    assert r.status_code == 202
    bid = r.json()["batch_id"]
    assert bid
    for _ in range(100):
        snap = client.get("/experiments/{}".format(bid)).json()
        if snap["job"] is None or not snap["job"]["running"]:
            break
        time.sleep(0.05)
    assert snap["rows"] == 4 and len(snap["summary"]) == 2
    assert {p["mode"] for p in snap["points"]} == {"normal", "watermarked"}
    lst = client.get("/experiments").json()
    assert lst["batches"][0]["batch_id"] == bid and lst["batches"][0]["settings"]["seed_base"] == 9
    assert client.post("/experiments/{}/stop".format(bid)).status_code == 409   # already finished
    ex = client.get("/experiments/{}/export".format(bid))
    assert ex.status_code == 200 and "flagged_rate" in ex.text
    assert client.get("/experiments/zzz").status_code == 404
