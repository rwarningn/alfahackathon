import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

import app
from scoring import assess

GOOD = dict(company="ООО Вектор (синтетика)", amount=1000000, term_months=12,
            monthly_revenue=1200000, monthly_expenses=800000,
            existing_payment=20000, business_months=24)


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        app.DB_PATH = Path(cls.temp.name) / "test.db"
        app.init_db()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def request(self, method, path, body=None, cookie=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), response.getheader("Set-Cookie")
        connection.close()
        return result

    def login(self, username):
        status, _, cookie = self.request("POST", "/api/login", dict(username=username, password=username + "-demo"))
        self.assertEqual(status, 200)
        return cookie.split(";")[0]

    def test_full_pipeline_and_permissions(self):
        self.assertEqual(self.request("GET", "/api/applications")[0], 401)
        client, bank, other = self.login("client"), self.login("bank"), self.login("other")
        status, created, _ = self.request("POST", "/api/applications", GOOD, client)
        self.assertEqual(status, 201)
        identifier = created["id"]
        transition = f"/api/applications/{identifier}/transition"
        self.assertEqual(self.request("GET", "/api/applications", cookie=other)[1], [])
        self.assertEqual(self.request("POST", "/api/applications", GOOD, bank)[0], 403)
        self.assertEqual(self.request("POST", transition, dict(status="review", comment="Проверяем данные"), client)[0], 403)
        self.assertEqual(self.request("POST", transition, dict(status="approved", comment="Можно одобрить"), bank)[0], 409)
        self.assertEqual(self.request("POST", transition, dict(status="review", comment="Проверяем показатели"), bank)[0], 200)
        self.assertEqual(self.request("POST", transition, dict(status="approved", comment="Показатели проверены"), bank)[0], 200)
        self.assertEqual(self.request("POST", transition, dict(status="declined", comment="Повторное решение"), bank)[0], 409)
        saved = next(a for a in self.request("GET", "/api/applications", cookie=client)[1] if a["id"] == identifier)
        self.assertEqual(saved["status"], "approved")
        self.assertEqual(len(saved["events"]), 3)
        # Reinitialization does not destroy persisted data.
        app.init_db()
        with app.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM applications WHERE id=?", (identifier,)).fetchone()[0], "approved")

    def test_validation(self):
        client = self.login("client")
        for invalid in ({**GOOD, "amount": -1}, {**GOOD, "amount": float("nan")},
                        {**GOOD, "term_months": 3.5}, {**GOOD, "company": ""},
                        {**GOOD, "business_months": True}, {**GOOD, "extra": 1}):
            self.assertEqual(self.request("POST", "/api/applications", invalid, client)[0], 400)

    def test_decline_pipeline(self):
        client, bank = self.login("client"), self.login("bank")
        _, created, _ = self.request("POST", "/api/applications", {**GOOD, "monthly_expenses": 1150000}, client)
        self.assertEqual(created["assessment"]["recommendation"], "decline")
        path = f"/api/applications/{created['id']}/transition"
        self.assertEqual(self.request("POST", path, dict(status="review", comment="Проверка потока"), bank)[0], 200)
        status, result, _ = self.request("POST", path, dict(status="declined", comment="Недостаточный денежный поток (демо)"), bank)
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "declined")
        self.assertEqual(len(result["events"]), 3)

    def test_rules_are_explainable(self):
        good = assess(GOOD)
        self.assertEqual(good["recommendation"], "approve")
        self.assertAlmostEqual(good["monthly_payment"], 94559.60, places=2)
        self.assertEqual(assess({**GOOD, "monthly_expenses": 1150000})["recommendation"], "decline")
        self.assertEqual(assess({**GOOD, "business_months": 9})["recommendation"], "review")


if __name__ == "__main__":
    unittest.main()
