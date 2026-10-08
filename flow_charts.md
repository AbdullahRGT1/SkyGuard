# SkyGuard Flow Charts

This document collects the main runtime flows for the SkyGuard operator/streamer system.
The important architectural rule is unchanged: streamer startup is not stream startup.
The streamer must stay in `READY_WAITING` and must not open the camera, encode frames,
or transmit video until an authenticated `START_STREAM` command is accepted.

## 1. End-to-End System Flow

```mermaid
flowchart TD
    A["Start SkyGuard"] --> B{"Which app starts?"}

    B -- "Streamer desktop" --> S1["Create QApplication"]
    B -- "Raspberry Pi streamer" --> R1["Start terminal app"]
    B -- "Operator desktop" --> O1["Create QApplication"]

    S1 --> S2["ThemeManager.initialize(auto)"]
    S2 --> S3["Build StreamerMainWindow<br/>Status + Logs"]
    S3 --> S4["Load StreamerConfig from env<br/>host, control port, video port, PIN"]
    S4 --> S5["Create StreamerStateMachine"]
    S5 --> S6["Create StreamService"]
    S6 --> S7["Start StreamerControlServer<br/>background asyncio thread"]
    S7 --> S_READY["READY_WAITING<br/>camera closed, UDP stopped"]

    R1 --> R2["Load StreamerConfig from env"]
    R2 --> R3["Create StateMachine + StreamService + ControlServer"]
    R3 --> R4["Print listening address and video port"]
    R4 --> S_READY

    O1 --> O2["ThemeManager.initialize(auto)"]
    O2 --> O3["Build OperatorMainWindow<br/>Dashboard / Preview / Logs / Settings"]
    O3 --> O4["Load OperatorSettingsStore<br/>APPDATA SkyGuard, legacy fallback"]
    O4 --> O5["Create VideoReceiver<br/>Create AiProcessor<br/>Create ViolationCaptureManager"]
    O5 --> O6["Operator enters streamer address + 4 digit PIN"]

    O6 --> C1["Parse ControlEndpoint"]
    C1 --> C2["Start OperatorControlClient<br/>background asyncio thread"]
    C2 --> C3["Open WebSocket to streamer<br/>TCP 8765 by default"]
    C3 --> C4["Challenge-response authentication"]
    C4 --> C5{"Auth OK?"}

    C5 -- "No" --> C_ERR["Connection ERROR<br/>log auth failure"]
    C_ERR --> O6
    C5 -- "Yes" --> C_OK["AUTHENTICATED"]
    C_OK --> C_STATE["Streamer sends STATE"]
    S_READY --> C_STATE

    C_STATE --> O_START{"Operator clicks Start Stream?"}
    O_START -- "No" --> C_STATE
    O_START -- "Yes" --> M1["Operator starts local UDP receiver<br/>0.0.0.0:5004 by default"]
    M1 --> M2["Send START_STREAM<br/>payload: video_port + video_settings"]
    M2 --> M3["Streamer validates state<br/>READY_WAITING only"]
    M3 --> M4["Streamer enters STARTING"]
    M4 --> M5["Open camera only now"]
    M5 --> M6["Encode frames as JPEG"]
    M6 --> M7["Chunk frames with video_packets.py"]
    M7 --> M8["Send UDP packets to operator host:port"]
    M8 --> M9["Streamer enters STREAMING"]
    M9 --> M10["Operator reassembles UDP packets"]
    M10 --> M11["Decode JPEG to QImage"]
    M11 --> M12{"AI enabled and ready?"}
    M12 -- "No" --> M_RAW["Render RAW preview"]
    M12 -- "Yes" --> M_AI["Submit latest frame to AI worker"]
    M_AI --> M_AI2["YOLO inference + cvzone drawing"]
    M_AI2 --> M_AI3["Render annotated preview"]
    M_RAW --> M_SYNC["Update preview badges<br/>mirror to fullscreen if open"]
    M_AI3 --> M_SYNC
    M_AI2 --> M_VIOL{"Violation capture enabled?"}
    M_VIOL -- "No" --> M_LOOP["Continue receiving frames"]
    M_VIOL -- "Yes" --> M_SAVE{"Violation + face policy passes?"}
    M_SAVE -- "No" --> M_LOOP
    M_SAVE -- "Yes" --> M_IMG["Save RAW JPG in Images/"]
    M_IMG --> M_SMART{"Smart Alerts enabled?"}
    M_SMART -- "Yes" --> M_QUEUE["Queue image path + YOLO violations<br/>for Smart Alerts"]
    M_SMART -- "No" --> M_LOOP
    M_QUEUE --> M_LOOP
    M_SYNC --> M_LOOP
    M_LOOP --> O_STOP{"STOP_STREAM or close app?"}
    O_STOP -- "No" --> M10
    O_STOP -- "STOP_STREAM" --> STOP1["Operator sends STOP_STREAM"]
    STOP1 --> STOP2["Operator stops UDP receiver"]
    STOP2 --> STOP3["Streamer enters STOPPING"]
    STOP3 --> STOP4["Stop sender thread<br/>release camera and UDP socket"]
    STOP4 --> S_READY
    O_STOP -- "Close" --> SHUTDOWN["Stop AI, video receiver, control client/server"]
```

## 2. Control Channel, Authentication, and Command Flow

```mermaid
flowchart LR
    subgraph OP["OperatorControlClient"]
        OP_A["connect_background(endpoint, pin)"]
        OP_B["Create asyncio loop<br/>operator-control-client thread"]
        OP_C["connect(uri)<br/>ping_interval=10"]
        OP_D["Receive AUTH_CHALLENGE<br/>salt + nonce"]
        OP_E["sign_challenge(pin, salt, nonce)"]
        OP_F["Send AUTH_RESPONSE<br/>pin_proof"]
        OP_G["Receive AUTH_OK or AUTH_FAILED"]
        OP_H["Set connection AUTHENTICATED"]
        OP_I["Send START_STREAM<br/>video_port + video_settings"]
        OP_J["Send STOP_STREAM"]
        OP_K["Handle STATE / ERROR / LOG"]
    end

    subgraph STREAM["StreamerControlServer"]
        ST_A["start_background()"]
        ST_B["Create asyncio loop<br/>streamer-control-server thread"]
        ST_C["serve(_handle_client)<br/>0.0.0.0:8765"]
        ST_D["Transition READY_WAITING"]
        ST_E["Create nonce"]
        ST_F["Send AUTH_CHALLENGE<br/>salt + nonce"]
        ST_G["Verify pin_proof<br/>verify_challenge_response"]
        ST_H{"Valid PIN proof?"}
        ST_I["Send AUTH_OK"]
        ST_J["Send AUTH_FAILED<br/>close command path"]
        ST_K["Handle START_STREAM"]
        ST_L["Handle STOP_STREAM"]
        ST_M["Handle HEARTBEAT"]
        ST_N["Send STATE or ERROR"]
    end

    subgraph SHARED["Shared Protocol"]
        MSG["ControlMessage JSON<br/>type, payload, request_id, timestamp"]
        TYPES["MessageType<br/>AUTH_CHALLENGE, AUTH_RESPONSE,<br/>AUTH_OK, START_STREAM, STOP_STREAM,<br/>HEARTBEAT, STATE, ERROR"]
        SEC["security.py<br/>PBKDF2 PIN key + HMAC challenge"]
    end

    OP_A --> OP_B --> OP_C
    ST_A --> ST_B --> ST_C --> ST_D
    OP_C <-->|"WebSocket TCP 8765"| ST_C
    ST_E --> ST_F --> OP_D --> OP_E --> OP_F --> ST_G --> ST_H
    ST_H -- "No" --> ST_J --> OP_G
    OP_G -- "Auth failed" --> OP_A
    ST_H -- "Yes" --> ST_I --> OP_G --> OP_H
    OP_H --> OP_I
    OP_H --> OP_J
    OP_H --> OP_K
    OP_I --> ST_K
    OP_J --> ST_L
    OP_K --> ST_N
    ST_M --> ST_N
    ST_N --> OP_K

    MSG -.-> OP_A
    MSG -.-> ST_K
    TYPES -.-> MSG
    SEC -.-> OP_E
    SEC -.-> ST_G
```

## 3. Streamer Lifecycle and State Machine Flow

```mermaid
flowchart TD
    A["Streamer process starts"] --> B["Load StreamerConfig.from_env()"]
    B --> C["PIN source check<br/>SKYGUARD_PIN, legacy SIMPLE_STREAM_PIN, or dev default"]
    C --> D["Create StreamerStateMachine<br/>initial BOOTING"]
    D --> E["Create StreamService<br/>camera/socket not opened yet"]
    E --> F["Create StreamerControlServer"]
    F --> G["Start background WebSocket server"]
    G --> H["Transition READY_WAITING"]

    H --> I{"Control message received?"}
    I -- "AUTH_RESPONSE before challenge<br/>or invalid command" --> E1["Send ERROR"]
    E1 --> H
    I -- "HEARTBEAT" --> HB["Send current STATE"]
    HB --> H
    I -- "START_STREAM" --> J{"Current state in START_ALLOWED_FROM?"}
    J -- "No" --> E2["Send ERROR INVALID_STATE"]
    E2 --> H
    J -- "Yes" --> K["Read operator remote host<br/>Read video_port<br/>Validate VideoSettings"]
    K --> L["Transition STARTING"]
    L --> M["Open OpenCV camera"]
    M --> N{"Camera opened and returned frame?"}
    N -- "No" --> E3["Release resources<br/>Transition ERROR then READY_WAITING<br/>Send START_FAILED"]
    E3 --> H
    N -- "Yes" --> O["Create UDP socket<br/>increase send buffer"]
    O --> P["Start streamer-video-sender thread"]
    P --> Q["Transition STREAMING<br/>Send STATE STREAMING"]

    Q --> R{"Sender loop"}
    R --> S["Read camera frame"]
    S --> T{"Frame OK?"}
    T -- "No" --> U["Log throttled read failure<br/>retry"]
    U --> R
    T -- "Yes" --> V["JPEG encode with quality setting"]
    V --> W{"Encode OK?"}
    W -- "No" --> R
    W -- "Yes" --> X["Increment frame_id"]
    X --> Y["iter_frame_packets(frame_id, bytes)"]
    Y --> Z["sendto(packet, operator host:port)"]
    Z --> AA{"Stop requested or send error?"}
    AA -- "No" --> AB["Sleep to match requested FPS"]
    AB --> R
    AA -- "Send error" --> E4["Log UDP send failure<br/>break sender loop"]
    E4 --> AC["Await STOP_STREAM or shutdown cleanup"]
    AA -- "Stop requested" --> AC

    Q --> AD{"STOP_STREAM received?"}
    AD -- "No" --> Q
    AD -- "Yes" --> AE{"State in STOP_ALLOWED_FROM?"}
    AE -- "No" --> AF["Send current STATE"]
    AF --> Q
    AE -- "Yes" --> AG["Transition STOPPING"]
    AG --> AH["Set stop event<br/>join sender thread"]
    AH --> AI["Release camera<br/>close UDP socket"]
    AI --> AJ["Transition READY_WAITING"]
    AJ --> H

    H --> CLOSE{"App closing?"}
    CLOSE -- "No" --> I
    CLOSE -- "Yes" --> CL1["stop_background()"]
    CL1 --> CL2["stream_service.stop()"]
    CL2 --> CL3["Close WebSocket server"]
```

## 4. Operator UI, Connection, and Preview Flow

```mermaid
flowchart TD
    A["Operator process starts"] --> B["Create QApplication"]
    B --> C["ThemeManager.initialize(app, auto)"]
    C --> D["Build OperatorMainWindow"]
    D --> E["Load settings from OperatorSettingsStore"]
    E --> F{"Settings file exists?"}
    F -- "SkyGuard path" --> F1["Load APPDATA/SkyGuard/operator_settings.json"]
    F -- "Legacy fallback" --> F2["Load APPDATA/SIMPLE_STREAM/operator_settings.json"]
    F -- "No file or invalid JSON" --> F3["Use default OperatorSettings"]
    F1 --> G["Create UI pages<br/>Preview toolbar + fullscreen action"]
    F2 --> G
    F3 --> G
    G --> H["Create VideoReceiver"]
    H --> I["Create AiProcessor"]
    I --> J["Create ViolationCaptureManager"]
    J --> K["Configure AI from settings"]

    K --> L{"AI enabled?"}
    L -- "No" --> L1["AI status Disabled<br/>Preview mode RAW"]
    L -- "Yes" --> L2["Start AI worker<br/>status Loading"]

    L1 --> M["Operator enters address + PIN"]
    L2 --> M
    M --> N{"Address and 4 digit PIN valid?"}
    N -- "No" --> N1["Log validation message"]
    N1 --> M
    N -- "Yes" --> O["parse_control_endpoint"]
    O --> P{"Endpoint valid?"}
    P -- "No" --> P1["Log parse error"]
    P1 --> M
    P -- "Yes" --> Q["Create OperatorControlClient"]
    Q --> R["connect_background"]
    R --> S["Connection badge CONNECTING"]
    S --> T{"Authentication result"}
    T -- "Failed/error" --> T1["Connection badge ERROR then DISCONNECTED"]
    T1 --> M
    T -- "OK" --> U["Connection badge AUTHENTICATED"]
    U --> V["Receive streamer STATE"]
    V --> W["Update streamer badge"]

    W --> X{"User command"}
    X -- "Start Stream" --> Y["Reset violation capture"]
    Y --> Z["Start VideoReceiver on UDP 5004"]
    Z --> AA["Preview text STARTING / WAITING FOR VIDEO"]
    AA --> AB["Send START_STREAM with video_settings"]
    AB --> AC["Receive STATE STARTING / STREAMING"]
    AC --> AD["Preview receives frames"]
    AD --> AE["Display RAW or AI annotated frame"]
    AE --> AE1{"Fullscreen preview open?"}
    AE1 -- "No" --> X
    AE1 -- "Yes" --> AE2["Mirror latest frame<br/>sync stream, RAW/AI, alert badges"]
    AE2 --> X
    X -- "Full Screen" --> FS1["Open frameless fullscreen preview window"]
    FS1 --> FS2["Render same aspect-ratio preview<br/>Esc, F11, or Exit closes it"]
    FS2 --> X
    X -- "Stop Stream" --> AF["Send STOP_STREAM"]
    AF --> AG["Stop VideoReceiver"]
    AG --> AH["Preview text NO SIGNAL"]
    AH --> X
    X -- "Disconnect" --> AI["Close WebSocket client"]
    AI --> AJ["Connection badge DISCONNECTED"]
    AJ --> M
    X -- "Close app" --> AK["Stop preview timer"]
    AK --> AL["Stop AI worker"]
    AL --> AM["Stop VideoReceiver"]
    AM --> AN["Disconnect control client"]
```

## 5. Video Transport and Frame Reassembly Flow

```mermaid
flowchart LR
    subgraph STREAMER["Streamer Media Thread"]
        A["OpenCV VideoCapture"]
        B["Read frame"]
        C["cv2.imencode .jpg<br/>quality from VideoSettings"]
        D["Frame bytes"]
        E["packetize_frame / iter_frame_packets"]
        F["UDP sendto<br/>operator_host:5004"]
    end

    subgraph PACKET["Packet Format"]
        P1["frame_id"]
        P2["chunk_index"]
        P3["chunk_count"]
        P4["payload <= 1200 bytes"]
    end

    subgraph OPERATOR["Operator VideoReceiver Thread"]
        G["UDP socket bind<br/>0.0.0.0:5004"]
        H["recvfrom"]
        I["parse_packet"]
        J["Store chunk by frame_id"]
        K{"All chunks arrived?"}
        L["Drop stale frames<br/>older than 0.5s"]
        M["Trim pending frames<br/>max 8"]
        N["Join chunks in order"]
        O["np.frombuffer"]
        Q["cv2.imdecode"]
        R{"Decode OK?"}
        S["Convert BGR to QImage"]
        T["emit frame_received(QImage)"]
    end

    A --> B --> C --> D --> E --> F
    E -.-> P1
    E -.-> P2
    E -.-> P3
    E -.-> P4
    F -->|"UDP packet stream"| G
    G --> H --> I --> J --> K
    K -- "No" --> L --> M --> H
    K -- "Yes" --> N --> O --> Q --> R
    R -- "No" --> H
    R -- "Yes" --> S --> T
```

## 6. Operator Frame, AI, and Violation Capture Flow

```mermaid
flowchart TD
    A["VideoReceiver emits raw QImage"] --> B["_handle_received_frame(image)"]
    B --> C{"AI setting enabled<br/>and AiProcessor ready?"}

    C -- "No" --> D["Display raw frame"]
    D --> E["Preview badge RAW"]
    E --> F["Violation badge Alerts 0"]
    F --> G["Render timer paints aspect-ratio preview label"]
    G --> G1{"Fullscreen preview visible?"}
    G1 -- "No" --> G2["Return to receive loop"]
    G1 -- "Yes" --> G3["Set same QImage on fullscreen label"]
    G3 --> G2

    C -- "Yes" --> H["submit_frame(image)"]
    H --> I["AI worker stores latest frame only"]
    I --> J["Older pending frame is replaced"]
    J --> K["Worker wakes on frame_event"]
    K --> L["Convert QImage to BGR numpy"]
    L --> M["ImprovedYoloFrameProcessor.predict"]
    M --> N["Ultralytics YOLO inference"]
    N --> O["cvzone boxes/text + FPS overlay"]
    O --> P["Compute class_counts<br/>violation_count<br/>violation_summary"]
    P --> Q["Emit metrics<br/>AI ON | ms | FPS"]
    Q --> R["Emit violations_changed"]
    R --> S{"Detection events enabled?"}
    S -- "No" --> T["Emit annotated QImage"]
    S -- "Yes" --> U["Emit detection_processed<br/>raw image + counts + summary"]

    U --> V["ViolationCaptureManager.consider"]
    V --> W{"Capture enabled?"}
    W -- "No" --> T
    W -- "Yes" --> X{"Face count > 0<br/>and NO-Mask/NO-Helmet/NO-Safety Vest?"}
    X -- "No" --> Y["Mark inactive<br/>maybe reset after stabilization"]
    Y --> T
    X -- "Yes" --> Z{"Same face count as last capture?"}
    Z -- "Yes" --> T
    Z -- "No" --> AA{"Stabilization elapsed?"}
    AA -- "No" --> AB["Store pending face count"]
    AB --> T
    AA -- "Yes" --> AC["Save RAW JPG<br/>Images/timestamp_facesN_summary_raw.jpg"]
    AC --> T

    T --> AD["Convert annotated BGR to QImage"]
    AD --> AE["frame_processed signal"]
    AE --> AF["_display_frame"]
    AF --> G

    subgraph AI_LOAD["AI Load and Failure Paths"]
        L1["configure(AiSettings)"]
        L2{"settings.enabled?"}
        L3["Stop old worker<br/>status Disabled<br/>metrics RAW"]
        L4["Start worker<br/>status Loading"]
        L5["Import cv2, cvzone, numpy, torch, ultralytics"]
        L6{"Imports OK?"}
        L7["status Missing dependencies<br/>metrics AI ERROR"]
        L8["Resolve model path<br/>AI_layer/yolo/*.pt"]
        L9{"Model exists?"}
        L10["status Model error<br/>metrics AI ERROR"]
        L11["Resolve device auto/cpu/cuda<br/>load YOLO model<br/>warm up"]
        L12{"Model load OK?"}
        L13["status Ready<br/>metrics AI ON"]
        L14["status Model error<br/>metrics AI ERROR"]
    end

    L1 --> L2
    L2 -- "No" --> L3
    L2 -- "Yes" --> L4 --> L5 --> L6
    L6 -- "No" --> L7
    L6 -- "Yes" --> L8 --> L9
    L9 -- "No" --> L10
    L9 -- "Yes" --> L11 --> L12
    L12 -- "Yes" --> L13
    L12 -- "No" --> L14
    L13 -.->|"ready gate"| C
```

## 7. Smart Alerts InsightFace Batch Flow

```mermaid
flowchart TD
    A["Violation RAW image saved<br/>Images/*.jpg"] --> B["SmartAlertService.record_candidate"]
    B --> C["Background queue worker"]
    C --> D["Read YOLO violation counts<br/>NO_HELMET / NO_MASK / NO_SAFETY_VEST"]
    D --> E["InsightFace FaceAnalysis<br/>buffalo_l by default"]
    E --> F{"Real faces detected?"}
    F -- "No" --> G["Log diagnostics<br/>no observation stored"]
    F -- "Yes" --> H["Create normalized face embeddings<br/>bbox, confidence, quality"]
    H --> I["Store metadata in SQLite<br/>face_recognizer/smart_alerts.sqlite3"]
    I --> J{"Batch interval elapsed?"}
    J -- "No" --> K["Wait for more candidates"]
    J -- "Yes" --> L["Load pending observations"]
    L --> M["Cluster by violation_type<br/>and cosine similarity"]
    M --> N["Select best representative groups<br/>max_images_per_batch"]
    N --> O["Build n8n JSON payload<br/>summary + people + violations"]
    O --> P["Embed selected images as base64<br/>images[].data_base64 / data_url"]
    P --> Q["POST JSON to n8n webhook"]
    Q --> R["Mark events sent<br/>optionally prune sent records"]
```

Diagnostics format:

```text
Smart Alerts diagnostics | Image: X | Provider: insightface | Faces detected: N | Embeddings created: N
```

## 8. Settings, Persistence, and Live Stream Restart Flow

```mermaid
flowchart TD
    A["Open Settings navigation item"] --> A1{"SettingsPanel already built?"}
    A1 -- "No" --> A2["Create SettingsPanel lazily<br/>no AI environment probe yet"]
    A1 -- "Yes" --> B["Read current OperatorSettings"]
    A2 --> B
    B --> C["AI Environment panel"]
    B --> D["AI Detection controls"]
    B --> E["Video Settings controls"]
    B --> F["Violation Capture controls"]
    B --> G["Customize theme controls"]
    B --> SA["Smart Alerts controls"]

    C --> C1["Click Refresh<br/>probe Python environment in QProcess"]
    C1 --> C2["Parse JSON output<br/>python, torch, backend, CUDA, GPU,<br/>ultralytics, cvzone,<br/>insightface, onnxruntime providers"]
    C2 --> C3["Show environment status"]

    D --> D1["AI enabled"]
    D --> D2["Model selection from AI_layer/yolo/*.pt"]
    D --> D3["Device auto/cpu/cuda"]
    D --> D4["conf, iou, imgsz, verbose"]

    E --> E1["Camera index"]
    E --> E2["Resolution preset or custom width/height"]
    E --> E3["FPS"]
    E --> E4["JPEG quality"]

    F --> F1["Capture enabled"]
    F --> F2["Stabilization seconds"]

    G --> G1["Theme Auto / Light / Dark"]
    G1 --> G3["ThemeManager.set_preference"]

    SA --> SA1["Enable Smart Alerts"]
    SA --> SA2["Batch interval, max images,<br/>face similarity"]
    SA --> SA3["Group faces, send summary,<br/>delete temp records"]
    SA --> SA4["n8n webhook URL + Test"]

    D1 --> H["Click Apply"]
    D2 --> H
    D3 --> H
    D4 --> H
    E1 --> H
    E2 --> H
    E3 --> H
    E4 --> H
    F1 --> H
    F2 --> H
    SA1 --> H
    SA2 --> H
    SA3 --> H
    SA4 --> H

    H --> I["Build OperatorSettings"]
    I --> J["Validate VideoSettings, AiSettings,<br/>ViolationCaptureSettings, SmartAlertSettings"]
    J --> K{"Valid?"}
    K -- "No" --> K1["Reject invalid values<br/>keep UI usable"]
    K1 --> A
    K -- "Yes" --> L["OperatorSettingsStore.save"]
    L --> M["Write APPDATA/SkyGuard/operator_settings.json"]
    M --> N["Configure ViolationCaptureManager"]
    N --> N2["Configure SmartAlertService"]
    N2 --> O["Enable/disable AI detection events"]
    O --> P["AiProcessor.configure(settings.ai)"]
    P --> Q{"Streamer currently STREAMING?"}
    Q -- "No" --> R["Settings ready for next START_STREAM"]
    Q -- "Yes" --> S["Set restart_after_ready = True"]
    S --> T["Send STOP_STREAM"]
    T --> U["Streamer releases media and returns READY_WAITING"]
    U --> V["Operator receives READY_WAITING"]
    V --> W["Restart stream with updated video_settings"]
    W --> X["Send START_STREAM with new settings"]
```

## 9. AI Environment Installer Flow

```mermaid
flowchart TD
    A["Operator Settings<br/>AI Environment"] --> B["Click Refresh"]
    B --> C["Run environment_probe_code in QProcess"]
    C --> D["Collect Python executable"]
    D --> E["Try import torch"]
    E --> F["Detect torch version, CUDA availability, GPU name"]
    F --> G["Check ultralytics, cvzone,<br/>insightface, onnxruntime"]
    G --> G2["Read ONNX Runtime providers"]
    G2 --> H["Display backend + packages<br/>and ONNX providers"]

    A --> I{"Install backend?"}
    I -- "CPU" --> J["Confirm install"]
    I -- "CUDA" --> K["Confirm install"]
    J --> L["Launch setup_ai_cpu.ps1<br/>detached PowerShell"]
    K --> M["Launch setup_ai_cuda.ps1<br/>detached PowerShell"]
    L --> N["Detect running project Python processes"]
    M --> N
    N --> O["Ask user to close app/terminals if files are locked"]
    O --> P["Uninstall torch, torchvision, torchaudio"]
    P --> P2["Uninstall onnxruntime and onnxruntime-gpu"]
    P2 --> Q["Remove pip leftovers such as ~orch"]
    Q --> R{"Requested backend"}
    R -- "CPU" --> S["Install PyTorch from whl/cpu"]
    R -- "CUDA" --> T["Install PyTorch from whl/cu128"]
    S --> S2["Install requirements-ai-cpu.txt<br/>onnxruntime"]
    T --> T2["Install requirements-ai-cuda.txt<br/>onnxruntime-gpu"]
    S2 --> U["Install requirements-ai-common.txt<br/>ultralytics, cvzone, pillow,<br/>PyYAML, lap, insightface"]
    T2 --> U
    U --> V["Verify torch, YOLO,<br/>InsightFace, ONNX Runtime"]
    V --> W{"CUDA installer?"}
    W -- "No" --> X["CPU setup complete"]
    W -- "Yes" --> Y{"torch version not +cpu<br/>and cuda.is_available()"}
    Y -- "Yes" --> Z["CUDA setup complete"]
    Y -- "No" --> AA["Fail loudly<br/>leave PowerShell open"]
```

## 10. UI Theme and Shared Design Flow

```mermaid
flowchart TD
    A["App creates QApplication"] --> B["ThemeManager.initialize(app, auto)"]
    B --> C["Apply QFluentWidgets Theme.AUTO"]
    C --> D["Set theme color"]
    D --> E["Prepare solid top-level window<br/>stable background"]
    E --> F{"Effective theme"}
    F -- "Light" --> G["Load LIGHT_TOKENS"]
    F -- "Dark" --> H["Load DARK_TOKENS"]
    G --> I["Apply global QSS"]
    H --> I
    I --> J["Register themed widgets"]
    J --> K["ThemedPage refreshes on theme changes"]
    J --> L["ThemedStatusBadge applies semantic status colors"]
    J --> M["AcrylicGlowFrame paints panel/card surfaces"]
    M --> N["enterEvent / leaveEvent update hover state"]
    N --> O["paintEvent draws surface, border, hover overlay"]
    J --> P["CustomizeCard controls runtime theme"]
    J --> U["Preview page owns stream-info badge<br/>fullscreen action + aspect-ratio label"]
    U --> V["FullscreenPreviewWindow reuses theme tokens<br/>mirrors latest frame and badges"]
    P --> Q{"User changes theme?"}
    Q -- "No" --> R["Continue current UI"]
    Q -- "Yes" --> S["ThemeManager.set_preference"]
    S --> T["Refresh registered widgets"]
    T --> F
```

## 11. Error, Disconnect, and Shutdown Flow

```mermaid
flowchart TD
    A["Runtime event"] --> B{"Event type"}

    B -- "Control auth failed" --> C["Streamer sends AUTH_FAILED"]
    C --> D["Operator logs error"]
    D --> E["Connection state ERROR then DISCONNECTED"]

    B -- "Unknown control command" --> F["Streamer sends ERROR UNKNOWN_COMMAND"]
    F --> G["Operator logs streamer error"]
    G --> H["Streamer state shown as ERROR"]

    B -- "START_STREAM invalid state" --> I["Streamer sends ERROR INVALID_STATE"]
    I --> J["Operator stays connected"]
    J --> K["No camera opened"]

    B -- "Camera open/read startup failure" --> L["StreamService releases partial resources"]
    L --> M["State ERROR then READY_WAITING"]
    M --> N["Send START_FAILED and READY_WAITING"]

    B -- "UDP receive bind failure" --> O["VideoReceiver emits VIDEO_ERROR"]
    O --> P["Preview shows VIDEO ERROR"]

    B -- "AI import/model failure" --> Q["AiProcessor sets fatal_error"]
    Q --> R["AI status Missing dependencies or Model error"]
    R --> S["Preview continues RAW when frames arrive"]

    B -- "Operator closes" --> T["Stop preview render timer"]
    T --> U["AiProcessor.stop"]
    U --> V["VideoReceiver.stop"]
    V --> W["OperatorControlClient.disconnect"]

    B -- "Streamer closes" --> X["StreamerControlServer.stop_background"]
    X --> Y["StreamService.stop"]
    Y --> Z["Close WebSocket server<br/>release camera and UDP socket"]

    B -- "Network disconnect" --> AA["Control client catches ConnectionClosed"]
    AA --> AB["Clear connected event"]
    AB --> AC["Close websocket"]
    AC --> AD["Connection DISCONNECTED"]
```

## 12. Deployment Target Flow

```mermaid
flowchart LR
    A["SkyGuard codebase"] --> B{"Target device"}

    B -- "Operator PC" --> OP1["run_operator.py"]
    OP1 --> OP2["operator/app.py"]
    OP2 --> OP3["PySide6 + QFluentWidgets UI"]
    OP3 --> OP4["WebSocket control client"]
    OP3 --> OP5["UDP video receiver"]
    OP3 --> OP6["Optional AI packages<br/>torch, ultralytics, cvzone,<br/>insightface, onnxruntime"]

    B -- "Streamer PC" --> ST1["run_streamer.py"]
    ST1 --> ST2["streamer/app.py"]
    ST2 --> ST3["PySide6 + QFluentWidgets UI"]
    ST3 --> ST4["WebSocket control server"]
    ST3 --> ST5["OpenCV camera + UDP sender"]

    B -- "Raspberry Pi 5 Streamer" --> RP1["raspberry_pi_5/run.py"]
    RP1 --> RP2["streamer_app.py terminal app"]
    RP2 --> RP3["No Qt dependency"]
    RP3 --> RP4["WebSocket control server"]
    RP3 --> RP5["opencv-python-headless camera + UDP sender"]

    A --> SH1["shared/ protocol, state,<br/>settings, security, packetization"]
    SH1 -.-> OP4
    SH1 -.-> OP5
    SH1 -.-> ST4
    SH1 -.-> ST5
    SH1 -.-> RP4
    SH1 -.-> RP5
```
