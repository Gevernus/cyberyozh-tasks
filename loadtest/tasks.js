// Mixed read/write load against the task API. See docs/load-testing.md.
//
//   k6 run -e BASE_URL=https://tasks.example.com -e PASSWORD=... loadtest/tasks.js
//
// Users come from `manage.py seed_bulk` (load00000, load00001, ... sharing PASSWORD).
import http from "k6/http";
import { check, fail } from "k6";

const BASE_URL = (__ENV.BASE_URL || "https://localhost").replace(/\/$/, "");
const PASSWORD = __ENV.PASSWORD;
const USER_PREFIX = __ENV.USER_PREFIX || "load";
const USERS = Number(__ENV.USERS || 50);
const RATE = Number(__ENV.RATE || 50); // iterations started per second
const DURATION = __ENV.DURATION || "5m"; // keep under the access token lifetime (15m)
// Connect to this IP instead of resolving the host of BASE_URL, e.g. 127.0.0.1.
const HOST_IP = __ENV.HOST_IP;
const HOST = BASE_URL.replace(/^https?:\/\//, "").split(/[/:]/)[0];

const JSON_HEADERS = { "Content-Type": "application/json" };

export const options = {
  insecureSkipTLSVerify: __ENV.INSECURE === "1",
  hosts: HOST_IP ? { [HOST]: HOST_IP } : {},
  setupTimeout: "10m",
  scenarios: {
    mixed: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: Math.max(RATE, 10),
      maxVUs: RATE * 10,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{name:list}": ["p(95)<500"],
    "http_req_duration{name:list_next}": ["p(95)<500"],
    "http_req_duration{name:retrieve}": ["p(95)<300"],
    "http_req_duration{name:create}": ["p(95)<500"],
    "http_req_duration{name:complete}": ["p(95)<500"],
    "http_req_duration{name:comment}": ["p(95)<500"],
    checks: ["rate>0.99"],
  },
  summaryTrendStats: ["avg", "med", "p(95)", "p(99)", "max"],
};

export function setup() {
  if (!PASSWORD) fail("set PASSWORD, the password given to seed_bulk");
  const tokens = [];
  for (let n = 0; n < USERS; n++) {
    const username = `${USER_PREFIX}${String(n).padStart(5, "0")}`;
    const response = http.post(
      `${BASE_URL}/api/auth/token/`,
      JSON.stringify({ username, password: PASSWORD }),
      { headers: JSON_HEADERS, tags: { name: "login" } },
    );
    if (response.status !== 200) fail(`login ${username}: ${response.status} ${response.body}`);
    tokens.push(response.json("access"));
  }
  return { tokens };
}

function pick(items) {
  return items[Math.floor(Math.random() * items.length)];
}

export default function ({ tokens }) {
  const headers = { ...JSON_HEADERS, Authorization: `Bearer ${pick(tokens)}` };
  const request = (method, path, body, name) =>
    http.request(method, path.startsWith("http") ? path : `${BASE_URL}${path}`, body, {
      headers,
      tags: { name },
    });

  const roll = Math.random();
  if (roll < 0.6) {
    // Browse: first page, the next one by cursor, then one task.
    const page = request("GET", "/api/tasks/?page_size=20", null, "list");
    if (!check(page, { "list 200": (r) => r.status === 200 })) return;
    const next = page.json("next");
    if (next) {
      check(request("GET", next, null, "list_next"), { "next page 200": (r) => r.status === 200 });
    }
    const results = page.json("results");
    if (results.length) {
      const task = request("GET", `/api/tasks/${pick(results).id}/`, null, "retrieve");
      check(task, { "retrieve 200": (r) => r.status === 200 });
    }
  } else if (roll < 0.85) {
    // Write: create a task and complete it.
    const created = request(
      "POST",
      "/api/tasks/",
      JSON.stringify({ title: `k6 task ${Date.now()}`, priority: 2 }),
      "create",
    );
    if (!check(created, { "create 201": (r) => r.status === 201 })) return;
    const completed = request("POST", `/api/tasks/${created.json("id")}/complete/`, null, "complete");
    check(completed, { "complete 200": (r) => r.status === 200 });
  } else {
    // Discuss: comment on one of the newest tasks.
    const page = request("GET", "/api/tasks/?page_size=5", null, "list");
    if (!check(page, { "list 200": (r) => r.status === 200 })) return;
    const results = page.json("results");
    if (!results.length) return;
    const comment = request(
      "POST",
      `/api/tasks/${pick(results).id}/comments/`,
      JSON.stringify({ text: "Load test comment" }),
      "comment",
    );
    check(comment, { "comment 201": (r) => r.status === 201 });
  }
}
