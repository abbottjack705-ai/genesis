import datetime, hashlib, json, os, subprocess, sys

out = sys.argv[1]
os.makedirs(out, exist_ok=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


proc = subprocess.run(["w32tm", "/query", "/status"], capture_output=True, check=False)
stdout, stderr = proc.stdout, proc.stderr
with open(os.path.join(out, "W05_w32tm_query_status_stdout_raw.bin"), "wb") as fh:
    fh.write(stdout)
with open(os.path.join(out, "W05_w32tm_query_status_stderr_raw.bin"), "wb") as fh:
    fh.write(stderr)
decoded = stdout.decode("utf-8", errors="replace")
record = {
    "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "command": ["w32tm", "/query", "/status"],
    "returncode": proc.returncode,
    "stdout_bytes": len(stdout), "stdout_sha256": sha(stdout),
    "stderr_bytes": len(stderr), "stderr_sha256": sha(stderr),
    "crlf_pairs": stdout.count(b"\r\n"),
    "bare_cr": stdout.count(b"\r") - stdout.count(b"\r\n"),
    "bare_lf": stdout.count(b"\n") - stdout.count(b"\r\n"),
    "decoded_utf8_replace_sha256": sha(decoded.encode("utf-8")),
    "decoded_repr": repr(decoded),
}
with open(os.path.join(out, "W05_w32tm_query_status_capture.json"), "w", encoding="utf-8") as fh:
    json.dump(record, fh, indent=1)
print(json.dumps(record, indent=1))
