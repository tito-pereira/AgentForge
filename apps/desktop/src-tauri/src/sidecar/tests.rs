// SPDX-License-Identifier: MPL-2.0
use super::*;
use std::io::Cursor;
use std::sync::Mutex;

const READY: &str = r#"{"jsonrpc":"2.0","method":"system.ready","params":{"protocol_version":1}}"#;
const FIXTURE: &str = r#"
import json, sys, time
mode = sys.argv[1]
if mode == "timeout":
    time.sleep(30)
    raise SystemExit()
if mode == "malformed":
    print("not a frame", flush=True)
    raise SystemExit()
print('{"jsonrpc":"2.0","method":"system.ready","params":{"protocol_version":1}}', flush=True)
for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    request_id = request["id"]
    if method == "system.handshake":
        assert request["params"] == {"protocol_version": 2}
        methods = ["system.handshake","system.version","project.status","providers.status","system.shutdown"]
        if mode != "limited":
            methods.extend(["projects.list", "future.method"])
        if mode == "session_shutdown":
            methods.append("session.start")
        if mode == "missing_core":
            methods.remove("system.shutdown")
        result = {
            "protocol_version": 1 if mode == "mismatch" else 2,
            "version": "test",
            "methods": methods,
        }
    elif method == "system.shutdown":
        if mode == "session_shutdown":
            time.sleep(1.2)
        if mode == "ignore_shutdown":
            time.sleep(30)
        result = {"stopping": True}
    elif mode == "crash":
        raise SystemExit(4)
    elif mode == "wrong_id":
        result, request_id = {}, request_id + 1
    elif mode == "invalid_response":
        print("x" * 65537, flush=True)
        time.sleep(30)
        raise SystemExit()
    else:
        result = {"version": "test"}
    print(json.dumps({"jsonrpc":"2.0","id":request_id,"result":result}), flush=True)
    if method == "system.shutdown":
        print('{"jsonrpc":"2.0","method":"system.stopping","params":{}}', flush=True)
        break
"#;

fn no_events() -> EventSink {
    Arc::new(|_| {})
}

fn fixture_python() -> PathBuf {
    let executable = PathBuf::from(
        env::var_os("CORINTHOS_SIDECAR_TEST_PYTHON")
            .expect("set CORINTHOS_SIDECAR_TEST_PYTHON to the absolute test Python executable"),
    );
    assert!(valid_override(&executable));
    executable
}

fn fixture(mode: &str, timeout: Duration, events: EventSink) -> Result<(Sidecar, Handshake)> {
    Sidecar::launch(
        python_command(&fixture_python(), &["-c", FIXTURE, mode]),
        events,
        timeout,
    )
}

#[test]
fn framing_limits_and_truncated_streams() {
    let mut frame = vec![b'x'; MAX_FRAME_BYTES];
    frame.extend(b"\nnext\n");
    let mut stream = BufReader::with_capacity(11, Cursor::new(frame));
    assert_eq!(
        read_frame(&mut stream).unwrap().unwrap().len(),
        MAX_FRAME_BYTES
    );
    assert_eq!(read_frame(&mut stream).unwrap().unwrap(), b"next");
    assert!(read_frame(&mut stream).unwrap().is_none());
    let oversize = vec![b'x'; MAX_FRAME_BYTES + 1];
    assert_eq!(
        read_frame(&mut Cursor::new(oversize)).unwrap_err().kind(),
        io::ErrorKind::InvalidData
    );
    assert_eq!(
        read_frame(&mut Cursor::new(b"partial")).unwrap_err().kind(),
        io::ErrorKind::UnexpectedEof
    );
}

#[test]
fn decode_rejects_mixed_or_unrecognized_frames() {
    assert!(matches!(decode(READY.as_bytes()), Ok(Wire::Ready)));
    assert!(matches!(
        decode(br#"{"jsonrpc":"2.0","id":5,"result":{"version":"0.1.0"}}"#),
        Ok(Wire::Response(5, Ok(_)))
    ));
    assert!(matches!(
        decode(br#"{"jsonrpc":"2.0","id":5,"error":{"code":-32602,"message":"detail"}}"#),
        Ok(Wire::Response(
            5,
            Err("The Corinthos sidecar rejected the request.")
        ))
    ));
    for frame in [
        "{}",
        r#"{"jsonrpc":"2.0","id":1,"result":null,"error":null}"#,
        r#"{"jsonrpc":"2.0","method":"other.event","params":{}}"#,
    ] {
        assert!(decode(frame.as_bytes()).is_err());
    }
}

#[test]
fn handshake_failure_timeout_and_restart() {
    assert!(fixture("mismatch", HANDSHAKE_TIMEOUT, no_events()).is_err());
    assert!(fixture("missing_core", HANDSHAKE_TIMEOUT, no_events()).is_err());
    assert!(fixture("malformed", HANDSHAKE_TIMEOUT, no_events()).is_err());
    let start = Instant::now();
    assert!(fixture("timeout", Duration::from_millis(150), no_events()).is_err());
    assert!(start.elapsed() < Duration::from_secs(6));
    let (mut child, handshake) = fixture("normal", HANDSHAKE_TIMEOUT, no_events()).unwrap();
    assert_eq!(handshake.protocol_version, 2);
    assert!(handshake.supports("projects.list"));
    assert!(handshake.supports("future.method"));
    assert!(!handshake.supports("work.create"));
    assert_eq!(child.version().unwrap(), json!({"version":"test"}));
    child.shutdown().unwrap();
    assert!(child.child.try_wait().unwrap().unwrap().success());
}

#[test]
fn optional_methods_are_detected_without_rejecting_the_connection() {
    let (mut child, handshake) = fixture("limited", HANDSHAKE_TIMEOUT, no_events()).unwrap();
    assert!(handshake.supports("system.version"));
    assert!(!handshake.supports("projects.list"));
    child.shutdown().unwrap();
}

#[test]
fn wrong_response_or_crash_reaps_the_child() {
    for mode in ["wrong_id", "invalid_response", "crash"] {
        let (sender, events) = mpsc::channel();
        let (mut child, _) = fixture(
            mode,
            HANDSHAKE_TIMEOUT,
            Arc::new(move |event| {
                let _ = sender.send(event.method);
            }),
        )
        .unwrap();
        assert_eq!(
            events.recv_timeout(REQUEST_TIMEOUT).unwrap(),
            "system.ready"
        );
        assert!(child.version().is_err(), "{mode}");
        assert!(child.child.try_wait().unwrap().is_some(), "{mode}");
        assert_eq!(
            events.recv_timeout(REQUEST_TIMEOUT).unwrap(),
            "backend.disconnected"
        );
        assert!(events.try_recv().is_err());
    }
    let (mut child, _) = fixture("normal", HANDSHAKE_TIMEOUT, no_events()).unwrap();
    assert_eq!(child.version().unwrap(), json!({"version":"test"}));
    child.shutdown().unwrap();
}

#[test]
fn shutdown_terminates_and_reaps_an_unresponsive_child() {
    let (mut child, _) = fixture("ignore_shutdown", HANDSHAKE_TIMEOUT, no_events()).unwrap();
    let start = Instant::now();
    child.shutdown().unwrap();
    assert!(start.elapsed() < Duration::from_secs(6));
    assert!(!child.child.try_wait().unwrap().unwrap().success());
}

#[test]
fn session_shutdown_waits_for_backend_worker_cleanup() {
    let (mut child, handshake) =
        fixture("session_shutdown", HANDSHAKE_TIMEOUT, no_events()).unwrap();
    assert!(handshake.supports("session.start"));
    child.shutdown().unwrap();
    assert!(child.child.try_wait().unwrap().unwrap().success());
}

#[test]
#[ignore = "requires a private installed runtime and a prepared test project"]
fn private_runtime_repeated_cycles() {
    assert!(
        env::var_os("CORINTHOS_SIDECAR_PYTHON").is_none(),
        "exercise the actual private runtime resolution without an override"
    );
    let root = env::var("CORINTHOS_SIDECAR_TEST_PROJECT")
        .expect("set CORINTHOS_SIDECAR_TEST_PROJECT to a prepared test project");
    for cycle in 1..=10 {
        let event_log = Arc::new(Mutex::new(Vec::new()));
        let captured = Arc::clone(&event_log);
        let (mut child, handshake) = Sidecar::start(Arc::new(move |event| {
            captured.lock().unwrap().push(event.method)
        }))
        .unwrap();
        assert_eq!(handshake.version, "0.1.0");
        assert_eq!(handshake.protocol_version, 2);
        assert!(handshake.supports("projects.list"));
        assert!(handshake.supports("work.create"));
        assert!(handshake.supports("session.list"));
        assert!(
            child
                .request("session.list", json!({"root": &root}))
                .unwrap()["sessions"]
                .is_array()
        );
        assert_eq!(child.version().unwrap(), json!({"version": "0.1.0"}));
        let project = child.project_status(&root).unwrap();
        assert_eq!(project["exists"], true);
        assert_eq!(project["initialized"], true);
        assert!(child.providers_status().unwrap().is_object());
        assert!(child.request("projects.list", json!({})).unwrap()["projects"].is_array());
        let pid = child.child.id();
        child.shutdown().unwrap();
        assert!(child.child.try_wait().unwrap().unwrap().success());
        let deadline = Instant::now() + Duration::from_secs(1);
        loop {
            if event_log.lock().unwrap().as_slice() == ["system.ready", "system.stopping"] {
                break;
            }
            assert!(Instant::now() < deadline, "lifecycle events did not arrive");
            thread::sleep(Duration::from_millis(5));
        }
        println!("private runtime cycle {cycle}: process {pid} exited and was reaped");
    }
}
