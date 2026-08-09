/* global LivekitClient */
(() => {
  "use strict";

  const LOCALES = [
    { code: "zh-CN", name: "중국어", native: "中文", flag: "中" },
    { code: "zh-TW", name: "대만 중국어", native: "繁體中文", flag: "台" },
    { code: "vi-VN", name: "베트남어", native: "Tiếng Việt", flag: "Vi" },
    { code: "mn-MN", name: "몽골어", native: "Монгол", flag: "Мн" },
    { code: "en-US", name: "영어", native: "English", flag: "En" },
    { code: "ja-JP", name: "일본어", native: "日本語", flag: "日" },
    { code: "uk-UA", name: "우크라이나어", native: "Українська", flag: "Uk" },
  ];
  const ACTIVE_SESSION_KEY = "univoice.activeSession";

  const state = {
    mode: "professor",
    accessToken: sessionStorage.getItem("univoice.accessToken") || "",
    // 교수/학생 화면을 한 페이지에서 전환할 수 있으므로(데모 편의 기능) 두 LiveKit
    // 연결을 별도 참조로 관리한다. 단일 state.room을 공유하면 학생 화면으로 전환해
    // 입장하는 순간 교수 Room 참조가 덮어써져 마이크를 끌 방법이 없어지고, 교수 쪽
    // 재연결 이벤트 가드(`state.room !== room`)도 함께 죽는다.
    rooms: { professor: null, student: null },
    session: null,
    joinUrl: "",
    elapsedTimer: null,
    statusTimer: null,
    connectionStatusTimer: null,
    selectedStudentLocale: "vi-VN",
    activeSessions: [],
    micPausedByUser: false,
    endingSession: false,
  };

  const $ = (id) => document.getElementById(id);

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    if (options.auth !== false && state.accessToken) {
      headers.Authorization = `Bearer ${state.accessToken}`;
    }
    const response = await fetch(path, { ...options, headers });
    if (!response.ok) {
      let detail;
      try {
        detail = await response.json();
      } catch {
        detail = { message: response.statusText };
      }
      const error = new Error(Array.isArray(detail.message) ? detail.message.join(", ") : detail.message || "요청에 실패했습니다.");
      error.status = response.status;
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  function toast(message, type = "") {
    const el = $("toast");
    el.textContent = message;
    el.className = `toast show ${type}`;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.className = "toast"; }, 3200);
  }

  function setBusy(button, busy, label) {
    if (!button.dataset.label) button.dataset.label = button.innerHTML;
    button.disabled = busy;
    button.innerHTML = busy ? label : button.dataset.label;
  }

  function renderLocales() {
    $("professor-locales").innerHTML = LOCALES.map((locale, index) => `
      <label class="locale-option">
        <input type="checkbox" value="${locale.code}" ${index < 3 ? "checked" : ""}>
        <span>${locale.name}<small>${locale.native}</small></span>
      </label>
    `).join("");
    $("student-locales").innerHTML = LOCALES.map((locale) => `
      <label class="locale-option">
        <input type="radio" name="student-locale" value="${locale.code}" ${locale.code === state.selectedStudentLocale ? "checked" : ""}>
        <span><b>${locale.flag}</b><span>${locale.name}<small>${locale.native}</small></span></span>
      </label>
    `).join("");
    document.querySelectorAll('input[name="student-locale"]').forEach((input) => {
      input.addEventListener("change", () => {
        const locale = LOCALES.find((item) => item.code === input.value);
        state.selectedStudentLocale = input.value;
        $("selected-language").textContent = `${locale.flag} ${locale.name}`;
      });
    });
  }

  function showMode(mode) {
    state.mode = mode;
    const professor = mode === "professor";
    $("professor-app").classList.toggle("hidden", !professor);
    $("student-app").classList.toggle("hidden", professor);
    $("switch-mode").textContent = professor ? "학생 태블릿 화면" : "교수 모바일 화면";
    history.replaceState({}, "", professor ? "/professor" : `/join${location.search}`);
  }

  function getJoinData(token) {
    try {
      const payloadPart = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(payloadPart))));
    } catch {
      return null;
    }
  }

  async function loadCourses() {
    const courses = await api("/courses");
    const select = $("course-select");
    select.innerHTML = courses.length
      ? courses.map((course) => `<option value="${course.id}">${escapeHtml(course.name)}</option>`).join("")
      : '<option value="">등록된 과목이 없습니다</option>';
    $("professor-login").classList.add("hidden");
    $("professor-setup").classList.remove("hidden");
    return courses;
  }

  function readSavedSession() {
    try {
      const value = JSON.parse(sessionStorage.getItem(ACTIVE_SESSION_KEY) || "null");
      return value?.sessionId && value?.courseId ? value : null;
    } catch {
      return null;
    }
  }

  function saveActiveSession(session) {
    sessionStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify({
      sessionId: session.id,
      courseId: session.courseId,
      courseName: session.courseName,
    }));
  }

  function clearSavedSession() {
    sessionStorage.removeItem(ACTIVE_SESSION_KEY);
  }

  function courseNameFor(session, courses) {
    return courses.find((course) => course.id === session.courseId)?.name
      || readSavedSession()?.courseName
      || "진행 중인 수업";
  }

  function updateRecoveryControls() {
    const courseId = $("course-select").value;
    const matching = state.activeSessions.filter((session) => session.courseId === courseId);
    const button = $("recover-session");
    button.classList.toggle("hidden", matching.length === 0);
    button.disabled = matching.length > 1;
    button.textContent = matching.length > 1
      ? "활성 수업이 여러 개라 복구할 수 없습니다"
      : "진행 중 수업 복구";
  }

  async function refreshActiveSessions() {
    state.activeSessions = await api("/sessions/active");
    updateRecoveryControls();
    return state.activeSessions;
  }

  async function waitForWorkerReady(sessionId, { timeoutMs = 15000, intervalMs = 1000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const data = await api(`/sessions/${sessionId}/status`);
        const status = data.worker?.status;
        if (status === "ready") return true;
        if (status === "failed") return false;
      } catch {
        // Transient polling error; keep trying until the deadline.
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
    return false;
  }

  async function restoreProfessorSession(session, courses) {
    const button = $("recover-session");
    setBusy(button, true, "수업 연결을 복구하고 있습니다...");
    try {
      state.micPausedByUser = false;
      state.session = {
        ...session,
        courseName: courseNameFor(session, courses),
      };
      saveActiveSession(state.session);
      // /professor-token doubles as the recovery trigger: if the AI worker
      // died, the server republishes sessions.started here.
      const liveKit = await api(`/sessions/${session.id}/professor-token`, {
        method: "POST",
      });
      state.session.liveKit = liveKit;
      await connectProfessor(liveKit);
      await loadQr(session.id);
      enterProfessorLive();
      // LiveKit reconnecting doesn't mean the translation pipeline is back —
      // confirm the worker actually reports ready before claiming success.
      const workerReady = await waitForWorkerReady(session.id);
      if (workerReady) {
        toast("진행 중인 수업과 마이크 연결을 복구했습니다.");
      } else {
        toast("LiveKit 연결은 복구됐지만 번역 음성 파이프라인이 아직 준비되지 않았습니다. 잠시 후 상태를 확인해주세요.", "error");
      }
      return true;
    } catch (error) {
      await disconnectRoom("professor");
      clearSessionTimers();
      clearSavedSession();
      state.session = null;
      $("professor-live").classList.add("hidden");
      $("professor-setup").classList.remove("hidden");
      updateRecoveryControls();
      toast(`수업을 복구하지 못했습니다: ${error.message}`, "error");
      return false;
    } finally {
      setBusy(button, false);
      updateRecoveryControls();
    }
  }

  async function recoverProfessorSession(courses) {
    const sessions = await refreshActiveSessions();
    const saved = readSavedSession();
    if (!sessions.length) {
      clearSavedSession();
      return;
    }

    const savedMatch = saved
      ? sessions.find((session) => session.id === saved.sessionId && session.courseId === saved.courseId)
      : null;
    const candidate = savedMatch || (sessions.length === 1 ? sessions[0] : null);
    if (candidate) {
      $("course-select").value = candidate.courseId;
      updateRecoveryControls();
      await restoreProfessorSession(candidate, courses);
      return;
    }

    if (saved?.courseId && courses.some((course) => course.id === saved.courseId)) {
      $("course-select").value = saved.courseId;
    }
    clearSavedSession();
    updateRecoveryControls();
    toast("진행 중인 수업이 여러 개입니다. 복구할 과목을 선택해주세요.");
  }

  async function recoverSelectedSession() {
    const courseId = $("course-select").value;
    if (!courseId) return toast("복구할 과목을 선택해주세요.", "error");
    const sessions = await api(`/sessions/active?courseId=${encodeURIComponent(courseId)}`);
    state.activeSessions = [
      ...state.activeSessions.filter((session) => session.courseId !== courseId),
      ...sessions,
    ];
    updateRecoveryControls();
    if (!sessions.length) {
      clearSavedSession();
      return toast("이 과목에는 진행 중인 수업이 없습니다.", "error");
    }
    if (sessions.length > 1) {
      return toast("이 과목에 활성 수업이 여러 개 있어 자동 복구하지 않았습니다.", "error");
    }
    const courses = [...$("course-select").options].map((option) => ({
      id: option.value,
      name: option.textContent,
    }));
    await restoreProfessorSession(sessions[0], courses);
  }

  async function initializeProfessor() {
    const courses = await loadCourses();
    await recoverProfessorSession(courses);
  }

  async function login(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    setBusy(button, true, "로그인 중...");
    try {
      const result = await api("/auth/login", {
        method: "POST",
        auth: false,
        body: JSON.stringify({ email: $("email").value.trim(), password: $("password").value }),
      });
      if (result.role === "student") throw new Error("교수자 계정으로 로그인해주세요.");
      state.accessToken = result.accessToken;
      sessionStorage.setItem("univoice.accessToken", result.accessToken);
      await initializeProfessor();
      toast("로그인되었습니다.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function startSession() {
    const button = $("start-session");
    const courseId = $("course-select").value;
    const targetLocales = [...document.querySelectorAll("#professor-locales input:checked")].map((input) => input.value);
    if (!courseId) return toast("시작할 과목을 선택해주세요.", "error");
    if (!targetLocales.length) return toast("번역 언어를 하나 이상 선택해주세요.", "error");
    let createdSession = null;
    setBusy(button, true, "수업을 준비하고 있습니다...");
    try {
      const result = await api("/sessions/start", {
        method: "POST",
        body: JSON.stringify({ courseId, targetLocales }),
      });
      createdSession = result.session;
      state.micPausedByUser = false;
      state.session = result.session;
      state.session.liveKit = result.liveKit;
      state.session.courseName = $("course-select").selectedOptions[0].textContent;
      saveActiveSession(state.session);
      state.activeSessions = [
        ...state.activeSessions.filter((session) => session.id !== result.session.id),
        result.session,
      ];
      await connectProfessor(result.liveKit);
      await loadQr(result.session.id);
      enterProfessorLive();
    } catch (error) {
      if (state.rooms.professor) await disconnectRoom("professor");
      if (createdSession) {
        state.session = null;
        await refreshActiveSessions().catch(() => undefined);
      }
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function syncProfessorMicrophone(room) {
    if (state.rooms.professor !== room) return;
    const shouldEnable = !state.micPausedByUser;
    if (room.localParticipant.isMicrophoneEnabled !== shouldEnable) {
      await room.localParticipant.setMicrophoneEnabled(shouldEnable);
    }
    $("mic-message").textContent = shouldEnable ? "ON" : "PAUSED";
  }

  async function connectProfessor(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({
      adaptiveStream: true,
      dynacast: true,
    });
    state.rooms.professor = room;
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      let data;
      try {
        data = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      if (topic === "stt" && data.text) {
        $("professor-transcript").textContent = data.text;
      } else if (topic === "caption" && data.sourceKo) {
        $("professor-transcript").textContent = data.sourceKo;
      }
    });
    room.on(LivekitClient.RoomEvent.Reconnecting, () => {
      if (state.rooms.professor !== room) return;
      clearTimeout(state.connectionStatusTimer);
      $("session-status").innerHTML = "<i></i> 재연결 중";
    });
    room.on(LivekitClient.RoomEvent.Reconnected, async () => {
      if (state.rooms.professor !== room) return;
      $("session-status").innerHTML = "<i></i> 다시 연결됨";
      try {
        await syncProfessorMicrophone(room);
      } catch (error) {
        toast(`마이크 상태를 복구하지 못했습니다: ${error.message}`, "error");
      }
      state.connectionStatusTimer = setTimeout(() => {
        if (state.rooms.professor === room) {
          $("session-status").innerHTML = "<i></i> 수업 진행 중";
        }
      }, 2000);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      if (state.rooms.professor !== room) return;
      $("session-status").innerHTML = "<i></i> 연결 끊김";
      $("mic-message").textContent = "LiveKit 연결이 끊겼습니다.";
    });
    await room.connect(liveKit.liveKitUrl, liveKit.token);
    try {
      await syncProfessorMicrophone(room);
    } catch (error) {
      throw new Error(`마이크를 시작할 수 없습니다: ${error.message}`);
    }
  }

  async function loadQr(sessionId) {
    state.joinUrl = "";
    $("qr-image").removeAttribute("src");
    $("qr-loading").textContent = "QR 생성 중";
    $("qr-loading").classList.remove("hidden");
    try {
      const qr = await api(`/qr/${sessionId}`);
      state.joinUrl = qr.joinUrl;
      $("qr-image").src = qr.qrImage;
      $("qr-loading").classList.add("hidden");
    } catch (error) {
      $("qr-loading").textContent = "QR 생성 실패";
      toast(error.message, "error");
    }
  }

  function enterProfessorLive() {
    clearSessionTimers();
    $("professor-setup").classList.add("hidden");
    $("professor-live").classList.remove("hidden");
    $("live-course-name").textContent = state.session.courseName;
    $("session-status").innerHTML = "<i></i> 수업 진행 중";
    $("mic-message").textContent = state.micPausedByUser ? "PAUSED" : "ON";
    $("locale-count").textContent = `${state.session.targetLocales.length}개 언어`;
    $("material-link").textContent = `${state.session.courseName.replace(/\s+/g, "_")}_강의자료`;
    const startedAt = new Date(state.session.startedAt).getTime();
    const updateElapsed = () => {
      const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      $("elapsed").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
    };
    updateElapsed();
    state.elapsedTimer = setInterval(updateElapsed, 1000);
    pollSessionStatus();
    state.statusTimer = setInterval(pollSessionStatus, 3000);
  }

  async function pollSessionStatus() {
    if (!state.session) return;
    try {
      const data = await api(`/sessions/${state.session.id}/status`);
      const worker = data.worker;
      const labels = {
        starting: "시작 중",
        ready: "준비 완료",
        stopping: "종료 중",
        stopped: "종료됨",
        failed: "오류",
      };
      $("worker-status").textContent = worker ? labels[worker.status] || worker.status : "응답 대기";
    } catch {
      $("worker-status").textContent = "확인 불가";
    }
  }

  async function endSession() {
    if (state.endingSession || !state.session || !confirm("현재 수업을 종료할까요? 학생의 자막과 음성도 함께 종료됩니다.")) return;
    const button = $("end-session");
    const endingSessionId = state.session.id;
    state.endingSession = true;
    setBusy(button, true, "수업을 종료하고 있습니다...");
    try {
      await api(`/sessions/${endingSessionId}/end`, { method: "POST" });
      await disconnectRoom("professor");
      clearSessionTimers();
      clearSavedSession();
      state.activeSessions = state.activeSessions.filter((session) => session.id !== endingSessionId);
      state.session = null;
      state.joinUrl = "";
      state.micPausedByUser = false;
      $("professor-live").classList.add("hidden");
      $("professor-setup").classList.remove("hidden");
      $("qr-image").removeAttribute("src");
      $("qr-loading").textContent = "QR 생성 중";
      $("qr-loading").classList.remove("hidden");
      if ($("qr-dialog").open) $("qr-dialog").close();
      updateRecoveryControls();
      toast("수업이 안전하게 종료되었습니다.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.endingSession = false;
      setBusy(button, false);
    }
  }

  async function joinStudentSession() {
    const button = $("join-session");
    const joinToken = $("join-token").value.trim();
    const localeInput = document.querySelector('input[name="student-locale"]:checked');
    if (!joinToken) return toast("입장 토큰이 필요합니다. QR 링크로 다시 접속해주세요.", "error");
    if (!localeInput) return toast("번역 언어를 선택해주세요.", "error");
    const payload = getJoinData(joinToken);
    if (!payload?.sessionId) return toast("올바른 입장 토큰이 아닙니다.", "error");
    state.selectedStudentLocale = localeInput.value;
    setBusy(button, true, "강의실에 연결 중...");
    try {
      const liveKit = await api(`/sessions/${payload.sessionId}/token`, {
        method: "POST",
        auth: false,
        body: JSON.stringify({ joinToken, locale: state.selectedStudentLocale }),
      });
      await connectStudent(liveKit);
      $("student-join").classList.add("hidden");
      $("student-live").classList.remove("hidden");
      const locale = LOCALES.find((item) => item.code === state.selectedStudentLocale);
      $("student-locale-label").textContent = `${locale.name} · ${locale.native}`;
      $("slide-course-title").textContent = $("joined-session-label").textContent.replace(/^•\s*/, "") || "실시간 강의";
      toast("강의실에 입장했습니다.");
    } catch (error) {
      await disconnectRoom("student");
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  async function connectStudent(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({ adaptiveStream: true });
    state.rooms.student = room;
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication) => {
      if (track.kind !== LivekitClient.Track.Kind.Audio || publication.trackName !== `tts.${state.selectedStudentLocale}`) return;
      const audio = $("translation-audio");
      track.attach(audio);
      audio.play().catch(() => toast("화면을 한 번 눌러 음성 재생을 허용해주세요."));
      $("audio-status").textContent = "번역 음성 재생 중";
    });
    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
      track.detach();
      $("audio-status").textContent = "다음 번역 음성을 기다리는 중";
    });
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      handleStudentData(payload, topic);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      if (state.rooms.student !== room) return;
      $("audio-status").textContent = "연결이 종료되었습니다";
      toast("강의실 연결이 종료되었습니다.");
    });
    await room.connect(liveKit.liveKitUrl, liveKit.token);
  }

  function handleStudentData(payload, topic) {
    let data;
    try {
      data = JSON.parse(new TextDecoder().decode(payload));
    } catch {
      return;
    }
    if (data.locale !== state.selectedStudentLocale) return;
    if (topic === "caption" && data.type !== "caption.partial") {
      addCaption(data.text, data.sourceKo);
    }
    if (topic === "audio-status") {
      const labels = {
        queued: "번역 음성 준비 중",
        playing: "번역 음성 재생 중",
        completed: "다음 발화를 기다리는 중",
        failed: "음성 생성에 실패했습니다",
      };
      $("audio-status").textContent = labels[data.status] || "번역 음성 처리 중";
    }
  }

  function addCaption(text, sourceKo) {
    if (!text) return;
    const captions = $("captions");
    const empty = captions.querySelector(".caption-empty");
    if (empty) empty.remove();
    const item = document.createElement("div");
    item.className = "caption";
    if (sourceKo) {
      const source = document.createElement("span");
      source.className = "source";
      source.textContent = sourceKo;
      item.appendChild(source);
    }
    const content = document.createElement("span");
    content.className = "translated";
    content.textContent = text;
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
    item.append(content, time);
    captions.appendChild(item);
    while (captions.children.length > 3) captions.firstElementChild.remove();
    captions.scrollTop = captions.scrollHeight;
  }

  async function leaveStudentSession() {
    await disconnectRoom("student");
    $("student-live").classList.add("hidden");
    $("student-join").classList.remove("hidden");
    $("captions").innerHTML = '<div class="caption-empty">교수님의 발화를 기다리고 있습니다.<br>번역 자막이 이곳에 표시됩니다.</div>';
  }

  async function disconnectRoom(role) {
    const room = state.rooms[role];
    if (!room) return;
    state.rooms[role] = null;
    try {
      await room.disconnect();
    } catch {
      // The server may already have closed the room.
    }
  }

  function clearSessionTimers() {
    clearInterval(state.elapsedTimer);
    clearInterval(state.statusTimer);
    clearTimeout(state.connectionStatusTimer);
    state.elapsedTimer = null;
    state.statusTimer = null;
    state.connectionStatusTimer = null;
  }

  function logout() {
    sessionStorage.removeItem("univoice.accessToken");
    clearSavedSession();
    clearSessionTimers();
    void disconnectRoom("professor");
    state.accessToken = "";
    state.session = null;
    state.activeSessions = [];
    state.micPausedByUser = false;
    $("professor-live").classList.add("hidden");
    $("professor-setup").classList.add("hidden");
    $("professor-login").classList.remove("hidden");
  }

  function ensureLiveKit() {
    if (typeof LivekitClient === "undefined") {
      throw new Error("LiveKit 브라우저 SDK를 불러오지 못했습니다.");
    }
  }

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function initialize() {
    renderLocales();
    const query = new URLSearchParams(location.search);
    const token = query.get("token") || "";
    if (token) {
      $("join-token").value = token;
      const payload = getJoinData(token);
      $("joined-session-label").textContent = payload?.sessionId
        ? "• QR로 연결된 오늘의 실시간 강의"
        : "입장 정보가 올바르지 않습니다.";
    }
    const studentRoute = location.pathname === "/join" || location.pathname === "/student" || Boolean(token);
    showMode(studentRoute ? "student" : "professor");

    $("switch-mode").addEventListener("click", () => showMode(state.mode === "professor" ? "student" : "professor"));
    $("login-form").addEventListener("submit", login);
    $("start-session").addEventListener("click", startSession);
    $("recover-session").addEventListener("click", () => {
      recoverSelectedSession().catch((error) => toast(error.message, "error"));
    });
    $("course-select").addEventListener("change", updateRecoveryControls);
    $("end-session").addEventListener("click", endSession);
    $("logout").addEventListener("click", logout);
    $("join-session").addEventListener("click", joinStudentSession);
    $("leave-session").addEventListener("click", leaveStudentSession);
    $("mic-pause").addEventListener("click", async () => {
      if (!state.rooms.professor) return;
      const room = state.rooms.professor;
      state.micPausedByUser = true;
      try {
        await room.localParticipant.setMicrophoneEnabled(false);
        $("mic-message").textContent = "PAUSED";
        toast("마이크를 잠시 껐습니다.");
      } catch (error) {
        state.micPausedByUser = false;
        toast(`마이크를 끄지 못했습니다: ${error.message}`, "error");
      }
    });
    $("mic-resume").addEventListener("click", async () => {
      if (!state.rooms.professor) return;
      const room = state.rooms.professor;
      state.micPausedByUser = false;
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        $("mic-message").textContent = "ON";
        toast("마이크를 다시 켰습니다.");
      } catch (error) {
        state.micPausedByUser = true;
        toast(`마이크를 켜지 못했습니다: ${error.message}`, "error");
      }
    });
    const openQr = () => {
      if (typeof $("qr-dialog").showModal === "function") $("qr-dialog").showModal();
      else $("qr-dialog").setAttribute("open", "");
    };
    $("show-qr").addEventListener("click", openQr);
    $("show-qr-nav").addEventListener("click", openQr);
    $("close-qr").addEventListener("click", () => $("qr-dialog").close());
    $("focus-token").addEventListener("click", () => {
      $("join-token").focus();
      $("join-token").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("copy-link").addEventListener("click", async () => {
      if (!state.joinUrl) return;
      await navigator.clipboard.writeText(state.joinUrl);
      toast("입장 링크를 복사했습니다.");
    });
    window.addEventListener("beforeunload", () => {
      clearSessionTimers();
      for (const role of ["professor", "student"]) {
        const room = state.rooms[role];
        if (!room) continue;
        state.rooms[role] = null;
        room.disconnect();
      }
    });

    if (state.accessToken && state.mode === "professor") {
      initializeProfessor().catch(() => logout());
    }
  }

  initialize();
})();
