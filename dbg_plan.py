import httpx, json
payload = {
    "model": "x",
    "messages": [
        {"role": "system", "content": "Reply ONLY one JSON object."},
        {"role": "user", "content": "Goal:\nopen notepad\n\nChoose the next action."},
    ],
    "temperature": 0.1, "max_tokens": 200,
}
r = httpx.post("http://127.0.0.1:8091/v1/chat/completions", json=payload, timeout=120)
d = r.json()
msg = d["choices"][0]["message"]
print(json.dumps(msg, indent=2, ensure_ascii=False)[:1200])
