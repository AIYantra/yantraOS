"""Native PySide6 visual intent shell for YantraOS."""

import json
import os
import socket
import stat
import struct
import sys
import unicodedata
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont, QFontDatabase, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

EXECUTOR_SOCKET_PATH = "/run/yantra/executor.sock"
MAX_INSTRUCTION_CHARS = 2000
MAX_REQUEST_BYTES = 16384
MAX_RESPONSE_BYTES = 16384
SOCKET_TIMEOUT_SECS = 430.0
MIN_SOCKET_TIMEOUT_SECS = 1.0
MAX_SOCKET_TIMEOUT_SECS = 430.0
_PROHIBITED_INSTRUCTION_CHARS = frozenset("&|;$`><")
_ALLOWED_RESPONSE_STATUSES = frozenset({"REJECTED"})


def safe_display_text(value: Any, limit: int = 2000) -> str:
    """Remove controls that could spoof transcript direction or terminal state."""
    text = unicodedata.normalize("NFC", str(value))
    clean = "".join(
        char
        for char in text
        if (char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf", "Cs"})
    )
    return clean[:limit]


class ExternalActionSocketClient:
    """Request and verify the root executor's mandatory policy rejection."""

    def __init__(
        self,
        socket_path: str = EXECUTOR_SOCKET_PATH,
        timeout: float = SOCKET_TIMEOUT_SECS,
        *,
        verify_socket: bool = True,
    ) -> None:
        if not isinstance(socket_path, str) or not os.path.isabs(socket_path):
            raise ValueError("Executor socket path must be absolute.")
        if not isinstance(timeout, (int, float)) or not (
            MIN_SOCKET_TIMEOUT_SECS <= timeout <= MAX_SOCKET_TIMEOUT_SECS
        ):
            raise ValueError(
                f"Socket timeout must be between {MIN_SOCKET_TIMEOUT_SECS:.0f} "
                f"and {MAX_SOCKET_TIMEOUT_SECS:.0f} seconds."
            )
        self.socket_path = socket_path
        self.timeout = float(timeout)
        self.verify_socket = verify_socket

    @staticmethod
    def build_payload(instruction: str) -> dict[str, Any]:
        if not isinstance(instruction, str):
            raise ValueError("Instruction must be a string.")

        normalized = unicodedata.normalize("NFC", instruction).strip()
        if not normalized:
            raise ValueError("Instruction cannot be empty.")
        if len(normalized) > MAX_INSTRUCTION_CHARS:
            raise ValueError(
                f"Instruction exceeds {MAX_INSTRUCTION_CHARS} characters."
            )
        if any(
            (ord(char) < 32 and char not in "\n\t")
            or unicodedata.category(char) in {"Cc", "Cf", "Cs"}
            for char in normalized
        ):
            raise ValueError(
                "Instruction contains hidden or unsupported control characters."
            )
        if any(char in normalized for char in _PROHIBITED_INSTRUCTION_CHARS):
            raise ValueError(
                "Instruction contains characters prohibited by the executor schema."
            )

        return {
            "intent": "EXTERNAL_ACTION",
            "target": "",
            "action_payload": {
                "action": "computer_use_task",
                "instruction": normalized,
            },
        }

    def _verify_socket_path(self) -> None:
        try:
            metadata = os.lstat(self.socket_path)
        except OSError as exc:
            raise ConnectionError("Host executor socket is unavailable.") from exc
        if not stat.S_ISSOCK(metadata.st_mode):
            raise ConnectionError("Host executor path is not a UNIX socket.")
        if metadata.st_uid != 0:
            raise ConnectionError("Host executor socket is not owned by root.")
        if metadata.st_mode & (stat.S_IROTH | stat.S_IWOTH | stat.S_IXOTH):
            raise ConnectionError("Host executor socket permits access by other users.")

    @staticmethod
    def _verify_peer(connection: socket.socket) -> None:
        peer_cred = getattr(socket, "SO_PEERCRED", None)
        if peer_cred is None:
            raise ConnectionError("UNIX peer credential verification is unavailable.")
        try:
            raw = connection.getsockopt(socket.SOL_SOCKET, peer_cred, 12)
            _pid, uid, _gid = struct.unpack("3i", raw)
        except (OSError, struct.error) as exc:
            raise ConnectionError("Could not verify the host executor peer.") from exc
        if uid != 0:
            raise ConnectionError("Connected UNIX peer is not the root executor.")

    @staticmethod
    def _validate_response(response: Any) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise RuntimeError("Host executor response must be a JSON object.")
        status = response.get("status")
        if not isinstance(status, str) or status not in _ALLOWED_RESPONSE_STATUSES:
            raise RuntimeError("Root Host Executor must reject EXTERNAL_ACTION.")
        intent = response.get("intent")
        if intent not in {None, "EXTERNAL_ACTION"}:
            raise RuntimeError("Host executor response intent does not match the request.")
        if not isinstance(response.get("error"), str) or not response["error"]:
            raise RuntimeError("Host executor rejection is missing an explanation.")
        return response

    def execute(self, instruction: str) -> dict[str, Any]:
        payload = self.build_payload(instruction)
        request = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(request) > MAX_REQUEST_BYTES:
            raise ValueError("Encoded EXTERNAL_ACTION exceeds the executor payload limit.")

        if self.verify_socket:
            self._verify_socket_path()

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.socket_path)
            if self.verify_socket:
                self._verify_peer(connection)
            connection.sendall(request)

            response = bytearray()
            while len(response) <= MAX_RESPONSE_BYTES:
                chunk = connection.recv(min(4096, MAX_RESPONSE_BYTES + 1 - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if b"\n" in chunk:
                    break

        if not response:
            raise RuntimeError("Host executor closed the socket without a response.")
        if len(response) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Host executor response exceeded the size limit.")
        if b"\n" not in response:
            raise RuntimeError("Host executor returned an unterminated response.")

        response_line = bytes(response).split(b"\n", 1)[0]
        try:
            parsed = json.loads(response_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Host executor returned an invalid response.") from exc
        return self._validate_response(parsed)


class ExternalActionWorker(QObject):
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        client: ExternalActionSocketClient,
        instruction: str,
    ) -> None:
        super().__init__()
        self.client = client
        self.instruction = instruction

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.client.execute(self.instruction))
        except (OSError, RuntimeError, ValueError) as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Unexpected EXTERNAL_ACTION client failure.")


def mono_family() -> str:
    """Return JetBrains Mono when available, otherwise a platform monospace."""
    families = set(QFontDatabase.families())
    return "JetBrains Mono" if "JetBrains Mono" in families else "monospace"


def clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class CommandEdit(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.submit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TranscriptEntry(QFrame):
    def __init__(
        self,
        role: str,
        title: str,
        body: str,
        status: str = "normal",
        rich: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("role", role)
        self.setProperty("status", status)
        self.setObjectName("transcriptEntry")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        heading_row.setSpacing(8)

        marker = QLabel({"user": "Y>", "executor": "AI", "boot": "::"}[role])
        marker.setObjectName("entryMarker")
        marker.setFixedWidth(28)
        heading = QLabel(title.upper())
        heading.setObjectName("entryHeading")
        timestamp = QLabel("NOW")
        timestamp.setObjectName("entryTime")
        heading_row.addWidget(marker)
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        heading_row.addWidget(timestamp)
        layout.addLayout(heading_row)

        text = QLabel()
        text.setObjectName("entryBody")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setTextFormat(Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText)
        text.setText(body)
        layout.addWidget(text)


class YantraMainWindow(QMainWindow):
    command_submitted = Signal(str)

    def __init__(self, socket_client: ExternalActionSocketClient | None = None) -> None:
        super().__init__()
        self.setObjectName("yantraWindow")
        self.setWindowTitle("YantraOS - AI Executive")
        self.setMinimumSize(960, 640)
        self.resize(1440, 900)
        self._busy = False
        self._socket_client = socket_client or ExternalActionSocketClient()
        self._action_thread: QThread | None = None
        self._action_worker: ExternalActionWorker | None = None

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())

        workspace = QWidget()
        workspace.setObjectName("workspace")
        workspace_layout = QHBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        workspace_layout.addWidget(self._build_sidebar())
        workspace_layout.addWidget(self._build_terminal(), 1)
        workspace_layout.addWidget(self._build_right_rail())
        root_layout.addWidget(workspace, 1)
        root_layout.addWidget(self._build_footer())

        self._apply_stylesheet()
        self._populate_mock_transcript()
        self.command_submitted.connect(self._dispatch_external_action)
        self.composer.setFocus()

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(48)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 8, 0)
        layout.setSpacing(12)

        mark = QLabel("Y")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(24, 24)
        title = QLabel("YANTRA / OS")
        title.setObjectName("brandTitle")
        division = QLabel("EXECUTIVE SHELL")
        division.setObjectName("topMeta")

        session = QLabel("SESSION  /  YN-04A7-11")
        session.setObjectName("sessionId")
        session.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(mark)
        layout.addWidget(title)
        layout.addWidget(division)
        layout.addStretch(1)
        layout.addWidget(session)
        layout.addStretch(1)

        minimize = self._window_button("_", "Minimize")
        maximize = self._window_button("[]", "Maximize")
        close = self._window_button("X", "Close", danger=True)
        minimize.clicked.connect(self.showMinimized)
        maximize.clicked.connect(self._toggle_maximized)
        close.clicked.connect(self.close)
        layout.addWidget(minimize)
        layout.addWidget(maximize)
        layout.addWidget(close)
        return bar

    def _window_button(self, text: str, tooltip: str, danger: bool = False) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("dangerWindowButton" if danger else "windowButton")
        button.setToolTip(tooltip)
        button.setFixedSize(32, 28)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button

    def _toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(256)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        identity = QFrame()
        identity.setObjectName("identityBlock")
        identity_layout = QVBoxLayout(identity)
        identity_layout.setContentsMargins(12, 12, 12, 12)
        identity_layout.setSpacing(4)
        kernel = QLabel("KERNEL  v1.0.4")
        kernel.setObjectName("eyebrow")
        executive = QLabel("AI Executive")
        executive.setObjectName("sideTitle")
        state = QLabel("O  SYSTEM NOMINAL")
        state.setObjectName("nominal")
        identity_layout.addWidget(kernel)
        identity_layout.addWidget(executive)
        identity_layout.addWidget(state)
        layout.addWidget(identity)

        new_session = QPushButton("+  NEW_SESSION")
        new_session.setObjectName("newSession")
        new_session.setFixedHeight(40)
        new_session.clicked.connect(self.clear_session)
        layout.addWidget(new_session)

        layout.addWidget(self._section_label("WORKSPACE"))
        layout.addWidget(self._nav_button("01", "Executive", active=True))
        layout.addWidget(self._nav_button("02", "Memory"))
        layout.addWidget(self._nav_button("03", "Automations"))
        layout.addWidget(self._nav_button("04", "Artifacts"))

        layout.addWidget(self._section_label("ACTIVE THREADS"))
        layout.addWidget(self._thread_row("Y-041", "System audit", "LIVE"))
        layout.addWidget(self._thread_row("Y-038", "Release map", "12m"))
        layout.addWidget(self._thread_row("Y-029", "Model routing", "1h"))
        layout.addStretch(1)

        layout.addWidget(self._nav_button("H", "Health", detail="98.7%"))
        layout.addWidget(self._nav_button("S", "Settings"))
        return sidebar

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        label.setContentsMargins(4, 12, 0, 2)
        return label

    def _nav_button(
        self, code: str, label: str, active: bool = False, detail: str = ""
    ) -> QPushButton:
        text = f"{code:<3}  {label}"
        if detail:
            text += f"  {detail}"
        button = QPushButton(text)
        button.setProperty("active", active)
        button.setObjectName("navButton")
        button.setFixedHeight(36)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _thread_row(self, code: str, title: str, age: str) -> QWidget:
        row = QFrame()
        row.setObjectName("threadRow")
        row.setFixedHeight(44)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        indicator = QLabel("|")
        indicator.setObjectName("threadIndicator")
        labels = QVBoxLayout()
        labels.setSpacing(0)
        name = QLabel(title)
        name.setObjectName("threadName")
        number = QLabel(code)
        number.setObjectName("threadCode")
        labels.addWidget(name)
        labels.addWidget(number)
        age_label = QLabel(age)
        age_label.setObjectName("threadAge")
        layout.addWidget(indicator)
        layout.addLayout(labels)
        layout.addStretch(1)
        layout.addWidget(age_label)
        return row

    def _build_terminal(self) -> QWidget:
        terminal = QFrame()
        terminal.setObjectName("terminal")
        layout = QVBoxLayout(terminal)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        context = QFrame()
        context.setObjectName("contextBar")
        context.setFixedHeight(32)
        context_layout = QHBoxLayout(context)
        context_layout.setContentsMargins(16, 0, 16, 0)
        context_layout.setSpacing(12)
        path = QLabel("EXECUTIVE / PRIMARY")
        path.setObjectName("contextPath")
        self.context_status = QLabel("READY")
        self.context_status.setObjectName("contextStatus")
        context_layout.addWidget(path)
        context_layout.addStretch(1)
        context_layout.addWidget(QLabel("MODEL  AUTO"))
        context_layout.addWidget(self.context_status)
        layout.addWidget(context)

        self.transcript_scroll = QScrollArea()
        self.transcript_scroll.setObjectName("transcriptScroll")
        self.transcript_scroll.setWidgetResizable(True)
        self.transcript_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.transcript_host = QWidget()
        self.transcript_host.setObjectName("transcriptHost")
        self.transcript_layout = QVBoxLayout(self.transcript_host)
        self.transcript_layout.setContentsMargins(24, 20, 24, 20)
        self.transcript_layout.setSpacing(12)
        self.transcript_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.transcript_scroll.setWidget(self.transcript_host)
        layout.addWidget(self.transcript_scroll, 1)
        layout.addWidget(self._build_composer())
        return terminal

    def _build_composer(self) -> QWidget:
        composer_frame = QFrame()
        composer_frame.setObjectName("composerFrame")
        composer_frame.setMinimumHeight(104)
        outer = QVBoxLayout(composer_frame)
        outer.setContentsMargins(24, 12, 24, 12)
        outer.setSpacing(6)

        editor_shell = QFrame()
        editor_shell.setObjectName("editorShell")
        editor_layout = QHBoxLayout(editor_shell)
        editor_layout.setContentsMargins(12, 8, 8, 8)
        editor_layout.setSpacing(8)
        prompt = QLabel("Y>")
        prompt.setObjectName("composerPrompt")
        prompt.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.composer = CommandEdit()
        self.composer.setObjectName("composer")
        self.composer.setPlaceholderText("Issue a directive to the executive...")
        self.composer.setAcceptRichText(False)
        self.composer.setTabChangesFocus(True)
        self.composer.setMinimumHeight(50)
        self.composer.setMaximumHeight(84)
        self.send_button = QPushButton("SEND  ^ENTER")
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(116, 40)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.clicked.connect(self._submit_command)
        self.composer.submit_requested.connect(self._submit_command)
        editor_layout.addWidget(prompt)
        editor_layout.addWidget(self.composer, 1)
        editor_layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        outer.addWidget(editor_shell)

        hint = QLabel("ENTER  NEW LINE    CTRL+ENTER  EXECUTE    ESC  ABORT")
        hint.setObjectName("composerHint")
        outer.addWidget(hint)
        return composer_frame

    def _build_right_rail(self) -> QWidget:
        rail = QFrame()
        rail.setObjectName("rightRail")
        rail.setFixedWidth(48)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(4, 12, 4, 12)
        layout.setSpacing(8)

        for text, tip in (
            ("LOG", "Activity log"),
            ("MEM", "Memory inspector"),
            ("RUN", "Execution queue"),
        ):
            button = QPushButton(text)
            button.setObjectName("railButton")
            button.setToolTip(tip)
            button.setFixedSize(40, 40)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            layout.addWidget(button)
        layout.addStretch(1)
        level = QLabel("07\n%")
        level.setObjectName("railLevel")
        level.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(level)
        return rail

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("footer")
        footer.setFixedHeight(32)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(20)

        self.footer_state = QLabel("O  CORE ONLINE")
        self.footer_state.setObjectName("footerOnline")
        layout.addWidget(self.footer_state)
        layout.addWidget(QLabel("LATENCY  14ms"))
        layout.addWidget(QLabel("TOKENS  8,241 / 32k"))
        layout.addStretch(1)
        layout.addWidget(QLabel("CPU  08%"))
        layout.addWidget(QLabel("MEM  2.4GB"))
        layout.addWidget(QLabel("LOCAL  09:41:22"))
        return footer

    def _populate_mock_transcript(self) -> None:
        self._append_entry(
            "boot",
            "Kernel boot sequence",
            """<span style="color:#bac9cc">[09:40:01]</span> Loading executive runtime ........ <span style="color:#00e5ff;font-weight:700">OK</span><br>
<span style="color:#bac9cc">[09:40:02]</span> Mounting semantic memory .......... <span style="color:#00e5ff;font-weight:700">OK</span><br>
<span style="color:#bac9cc">[09:40:02]</span> Policy boundary verified .......... <span style="color:#00e5ff;font-weight:700">OK</span><br>
<span style="color:#bac9cc">[09:40:03]</span> Yantra kernel ready on local node.""",
            rich=True,
        )
        self.append_user_message(
            "Run a readiness audit. Summarize active services and flag anything that needs attention."
        )
        audit = """Readiness audit complete. The local executive is operational and all critical services are responding within policy limits.

SERVICE             STATE       LATENCY     LOAD
------------------------------------------------
Executive Core      READY          14 ms      8%
Semantic Memory     READY          21 ms     31%
Task Scheduler      READY           9 ms      4%
Artifact Store      READY          18 ms     12%
Policy Guard        READY           6 ms      2%

One advisory: semantic memory is approaching its compaction threshold. No immediate action is required. Recommended maintenance window: 18:00 local.

NEXT ACTION
$ yantra memory compact --preview"""
        self.append_executor_message(audit)
        self.append_user_message(
            "Show the proposed maintenance sequence without executing it."
        )
        sequence = """Preview generated. No system changes were made.

01  Snapshot active index       estimated  00:18
02  Validate snapshot           estimated  00:07
03  Compact dormant segments    estimated  01:42
04  Rebuild lookup cache        estimated  00:24
05  Verify integrity            estimated  00:11

Total estimated window: 2 minutes 42 seconds.
Approval remains required before execution."""
        self.append_executor_message(sequence, status="warning")

    def _append_entry(
        self,
        role: str,
        title: str,
        body: str,
        status: str = "normal",
        rich: bool = False,
    ) -> None:
        entry = TranscriptEntry(role, title, body, status, rich)
        self.transcript_layout.addWidget(entry)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        bar = self.transcript_scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def append_user_message(self, text: str) -> None:
        """Append a user-authored directive to the transcript."""
        self._append_entry("user", "Directive", text.strip() or "(empty directive)")

    def append_executor_message(self, text: str, status: str = "normal") -> None:
        """Append an executive response with normal, warning, or error status."""
        if status not in {"normal", "warning", "error"}:
            status = "normal"
        self._append_entry(
            "executor", "Executive response", text.strip() or "(no response)", status
        )

    def set_busy(self, busy: bool) -> None:
        """Reflect executor activity and lock command submission."""
        self._busy = bool(busy)
        self.composer.setEnabled(not self._busy)
        self.send_button.setEnabled(not self._busy)
        self.send_button.setText("WORKING..." if self._busy else "SEND  ^ENTER")
        self.context_status.setText("PROCESSING" if self._busy else "READY")
        self.context_status.setProperty("busy", self._busy)
        self.context_status.style().unpolish(self.context_status)
        self.context_status.style().polish(self.context_status)

    def clear_session(self) -> None:
        """Clear the transcript and restore a fresh local session marker."""
        clear_layout(self.transcript_layout)
        self._append_entry(
            "boot",
            "New session",
            "Local transcript cleared. Executive context is ready.",
        )
        self.composer.clear()
        self.composer.setFocus()

    def _submit_command(self) -> None:
        if self._busy:
            return
        command = self.composer.toPlainText().strip()
        if not command:
            return
        self.command_submitted.emit(command)
        self.composer.clear()

    @Slot(str)
    def _dispatch_external_action(self, instruction: str) -> None:
        if self._action_thread is not None:
            return

        try:
            self._socket_client.build_payload(instruction)
        except ValueError as exc:
            self.append_executor_message(str(exc), status="error")
            return

        self.append_user_message(instruction)
        self.append_executor_message(
            "Checking the root Host Executor policy. External actions are "
            "disabled at this privilege boundary.",
            status="warning",
        )
        self._start_action_worker(instruction)

    def _start_action_worker(self, instruction: str) -> None:
        self.set_busy(True)
        thread = QThread(self)
        worker = ExternalActionWorker(self._socket_client, instruction)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._on_action_completed)
        worker.failed.connect(self._on_action_failed)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._release_action_thread)
        self._action_thread = thread
        self._action_worker = worker
        thread.start()

    @Slot(dict)
    def _on_action_completed(self, response: dict[str, Any]) -> None:
        status = str(response.get("status", "UNKNOWN")).upper()
        detail = safe_display_text(response.get("error", "Policy rejection.")).strip()
        self.append_executor_message(
            f"computer_use_task / {status}\n{detail}", status="error"
        )

    @Slot(str)
    def _on_action_failed(self, message: str) -> None:
        self.append_executor_message(
            f"EXTERNAL_ACTION transport failure\n{safe_display_text(message)}",
            status="error",
        )

    @Slot()
    def _release_action_thread(self) -> None:
        thread = self._action_thread
        self._action_thread = None
        self._action_worker = None
        if thread is not None:
            thread.deleteLater()
        self.set_busy(False)
        self.composer.setFocus()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._action_thread is not None and self._action_thread.isRunning():
            self.append_executor_message(
                "An external action is still running. Wait for the executor "
                "response before closing the shell.",
                status="warning",
            )
            event.ignore()
            return
        super().closeEvent(event)

    def _apply_stylesheet(self) -> None:
        font = mono_family()
        self.setFont(QFont(font, 10))
        self.setStyleSheet(
            """
            * {
                font-family: "%s";
                color: #e5e2e1;
                font-size: 12px;
            }
            QMainWindow, #root, #workspace { background: #131313; }
            QToolTip {
                background: #201f1f; color: #e5e2e1;
                border: 1px solid #353534; padding: 4px;
            }
            #topBar {
                background: #1c1b1b; border-bottom: 1px solid #353534;
            }
            #brandMark {
                color: #0e0e0e; background: #00e5ff;
                font-weight: 800; font-size: 14px;
            }
            #brandTitle { font-weight: 800; letter-spacing: 2px; }
            #topMeta, #sessionId { color: #bac9cc; font-size: 10px; }
            #sessionId { letter-spacing: 1px; }
            #windowButton, #dangerWindowButton {
                border: 0; background: transparent; color: #bac9cc;
            }
            #windowButton:hover { background: #353534; color: #e5e2e1; }
            #dangerWindowButton:hover { background: #ffb4ab; color: #131313; }
            #sidebar {
                background: #1c1b1b; border-right: 1px solid #353534;
            }
            #identityBlock { background: #201f1f; border: 1px solid #353534; }
            #eyebrow, #sectionLabel, #threadCode, #threadAge {
                color: #bac9cc; font-size: 10px; letter-spacing: 1px;
            }
            #sideTitle { font-size: 16px; font-weight: 700; }
            #nominal { color: #00e5ff; font-size: 10px; }
            #newSession {
                text-align: left; padding-left: 12px; color: #131313;
                background: #00e5ff; border: 1px solid #00e5ff;
                font-weight: 800;
            }
            #newSession:hover { background: #00daf3; border-color: #00daf3; }
            #navButton {
                text-align: left; padding: 0 10px; border: 0;
                background: transparent; color: #bac9cc;
            }
            #navButton:hover { background: #201f1f; color: #e5e2e1; }
            #navButton[active="true"] {
                background: #3b494c; color: #e5e2e1;
                border-left: 2px solid #00e5ff;
            }
            #threadRow { background: transparent; }
            #threadRow:hover { background: #201f1f; }
            #threadIndicator { color: #00e5ff; font-weight: 800; }
            #threadName { color: #e5e2e1; }
            #terminal, #transcriptHost, #transcriptScroll {
                background: #0e0e0e; border: 0;
            }
            #contextBar {
                background: #131313; border-bottom: 1px solid #353534;
            }
            #contextBar QLabel { color: #bac9cc; font-size: 10px; }
            #contextPath { color: #e5e2e1; font-weight: 700; }
            #contextStatus {
                color: #00e5ff; border-left: 1px solid #353534;
                padding-left: 12px; font-weight: 700;
            }
            #contextStatus[busy="true"] { color: #ffba38; }
            QScrollBar:vertical {
                background: #131313; width: 8px; margin: 0;
            }
            QScrollBar::handle:vertical { background: #3b494c; min-height: 40px; }
            QScrollBar::handle:vertical:hover { background: #00daf3; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            #transcriptEntry {
                background: #131313; border: 1px solid #353534;
                border-left: 2px solid #3b494c;
            }
            #transcriptEntry[role="user"] {
                background: #1c1b1b; border-left-color: #00e5ff;
            }
            #transcriptEntry[role="executor"] { border-left-color: #bac9cc; }
            #transcriptEntry[status="warning"] { border-left-color: #ffba38; }
            #transcriptEntry[status="error"] { border-left-color: #ffb4ab; }
            #entryMarker { color: #00e5ff; font-weight: 800; }
            #transcriptEntry[role="boot"] #entryMarker { color: #bac9cc; }
            #transcriptEntry[status="warning"] #entryMarker { color: #ffba38; }
            #transcriptEntry[status="error"] #entryMarker { color: #ffb4ab; }
            #entryHeading { color: #bac9cc; font-size: 10px; letter-spacing: 1px; }
            #entryTime { color: #3b494c; font-size: 10px; }
            #entryBody { color: #e5e2e1; line-height: 1.45; }
            #composerFrame {
                background: #131313; border-top: 1px solid #353534;
            }
            #editorShell { background: #1c1b1b; border: 1px solid #3b494c; }
            #editorShell:focus-within { border-color: #00e5ff; }
            #composerPrompt { color: #00e5ff; font-weight: 800; padding-top: 4px; }
            #composer {
                background: transparent; border: 0; color: #e5e2e1;
                selection-background-color: #3b494c;
            }
            #composer:disabled { color: #3b494c; }
            #sendButton {
                background: #00e5ff; color: #131313; border: 0;
                font-weight: 800; font-size: 10px;
            }
            #sendButton:hover { background: #00daf3; }
            #sendButton:disabled { background: #353534; color: #bac9cc; }
            #composerHint { color: #3b494c; font-size: 9px; letter-spacing: 1px; }
            #rightRail {
                background: #1c1b1b; border-left: 1px solid #353534;
            }
            #railButton {
                background: transparent; border: 1px solid #353534;
                color: #bac9cc; font-size: 9px;
            }
            #railButton:hover { border-color: #00e5ff; color: #00e5ff; }
            #railLevel { color: #ffba38; font-size: 10px; padding: 8px 0; }
            #footer {
                background: #201f1f; border-top: 1px solid #353534;
            }
            #footer QLabel { color: #bac9cc; font-size: 9px; letter-spacing: 1px; }
            #footerOnline { color: #00e5ff; font-weight: 700; }
            """
            % font
        )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("YantraOS")
    app.setOrganizationName("Yantra")
    window = YantraMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
