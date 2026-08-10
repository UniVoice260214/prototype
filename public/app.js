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
    room: null,
    session: null,
    joinUrl: "",
    elapsedTimer: null,
    statusTimer: null,
    connectionStatusTimer: null,
    selectedStudentLocale: "vi-VN",
    activeSessions: [],
    micPausedByUser: false,
    endingSession: false,
    // 서버가 보내는 sequence 로 시간 역행(늦게 도착한 패킷)을 막는다.
    lastCaptionSequence: 0,
    lastProfSequence: 0,
    captionExpiryTimer: null,
    // 과목별 강의 자료 목록 (교수 화면)
    materials: [],
    // 학생 회원 로그인 (게스트 QR 입장과 별개)
    studentToken: sessionStorage.getItem("univoice.studentToken") || "",
    studentProfile: null,
    // 자막 스크롤백: 화면에서 사라진 자막도 세션 동안 보관한다.
    studentSessionId: "",
    captionHistory: [],
    // 자막 기록 다이얼로그가 교수/학생 어느 모드로 열렸는지 (세션 셀렉트 공유).
    historyRole: "student",
  };

  const CAPTION_HISTORY_MAX = 500;

  const $ = (id) => document.getElementById(id);

  // ── 자막 자동 스크롤 제어 (표시 전용) ────────────────────────────────
  // 새 발화가 오면 최신으로 자동 스크롤하되, 사용자가 위로 스크롤해 이전
  // 발화를 읽는 동안에는 멈추고 "최신 자막으로" 버튼만 띄운다. 하단 근처로
  // 직접 돌아오면 자동 스크롤이 다시 활성화된다.
  const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const NEAR_BOTTOM_PX = 48;

  function createCaptionScroller(containerId, jumpButtonId, onPinChange) {
    const container = $(containerId);
    const jump = $(jumpButtonId);
    const scroller = { pinned: true };
    const setPinned = (value) => {
      if (scroller.pinned === value) return;
      scroller.pinned = value;
      if (onPinChange) onPinChange(value);
    };
    const nearBottom = () =>
      container.scrollHeight - container.scrollTop - container.clientHeight < NEAR_BOTTOM_PX;
    const toLatest = () => {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: REDUCED_MOTION ? "auto" : "smooth",
      });
      setPinned(true);
      jump.classList.add("hidden");
    };
    container.addEventListener("scroll", () => {
      if (nearBottom()) {
        setPinned(true);
        jump.classList.add("hidden");
      } else {
        setPinned(false);
      }
    });
    jump.addEventListener("click", toLatest);
    scroller.onAppend = () => {
      if (scroller.pinned) toLatest();
      else jump.classList.remove("hidden");
    };
    scroller.reset = () => {
      setPinned(true);
      jump.classList.add("hidden");
    };
    // 명시적 자동 스크롤 toggle 용 외부 제어 (표시 전용)
    scroller.toLatest = toLatest;
    scroller.unpin = () => setPinned(false);
    return scroller;
  }

  let studentScroller = null;
  let profScroller = null;

  // ── 상태 배지 (표시 전용 헬퍼) ──────────────────────────────────────
  function setSessionStatus(label, tone) {
    const badge = $("session-status");
    badge.className = `status-badge ${tone}`;
    badge.innerHTML = `<i></i> ${escapeHtml(label)}`;
  }

  function setMicBadge(label, tone) {
    const badge = $("mic-message");
    badge.className = `status-badge ${tone}`;
    badge.innerHTML = `<i></i> ${escapeHtml(label)}`;
  }

  function updateMicUi(enabled) {
    setMicBadge(enabled ? "실시간 번역 중" : "일시정지됨", enabled ? "is-live" : "is-warn");
    $("mic-pause").classList.toggle("hidden", !enabled);
    $("mic-resume").classList.toggle("hidden", enabled);
  }

  // ── 학생 자막 패널 표시 상태 (표시 전용) ────────────────────────────
  // open: 목록 표시 / minimized: 최신 1건만(좁은 화면 overlay) / closed: 숨김.
  // closed 는 display:none 이라 aria-live 도 침묵한다 — 스크린리더 중복 없음.
  let transcriptViewState = "open";

  function setTranscriptState(next) {
    transcriptViewState = next;
    const live = $("student-live");
    live.classList.toggle("transcript-closed", next === "closed");
    live.classList.toggle("transcript-minimized", next === "minimized");
    $("transcript-toggle").setAttribute("aria-expanded", String(next !== "closed"));
    $("transcript-expand").setAttribute("aria-expanded", String(next === "open"));
    $("transcript-reopen").classList.toggle("hidden", next !== "closed");
  }

  function syncAutoscrollButton(pinned) {
    const button = $("autoscroll-toggle");
    button.setAttribute("aria-pressed", String(pinned));
    // 상태를 색이 아닌 텍스트로 구분한다 (접근성).
    button.textContent = pinned ? "자동 스크롤 켬" : "자동 스크롤 끔";
  }

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
        $("selected-language").textContent = `${locale.name} · ${locale.native}`;
        savePreferredLocale(input.value);
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
    await loadMaterials(select.value);
    return courses;
  }

  const INDEXING_LABELS = {
    pending: "인덱싱 대기",
    processing: "인덱싱 중",
    done: "인덱싱 완료",
    failed: "인덱싱 실패",
  };

  async function loadMaterials(courseId) {
    if (!courseId) {
      state.materials = [];
      renderMaterials();
      return;
    }
    try {
      state.materials = await api(`/materials?courseId=${encodeURIComponent(courseId)}`);
    } catch {
      state.materials = [];
    }
    renderMaterials();
  }

  function renderMaterials() {
    const list = $("material-list");
    $("material-count").textContent = state.materials.length ? `${state.materials.length}개` : "";
    list.innerHTML = "";
    if (!state.materials.length) {
      list.innerHTML = '<li class="material-empty">등록된 자료가 없습니다.</li>';
      return;
    }
    state.materials.forEach((material) => {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.className = "material-name";
      name.textContent = material.week
        ? `${material.week}주차 · ${material.originalFilename}`
        : material.originalFilename;
      const status = document.createElement("b");
      status.className = `material-status ${material.indexingStatus}`;
      status.textContent = INDEXING_LABELS[material.indexingStatus] || material.indexingStatus;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "material-remove";
      remove.textContent = "삭제";
      remove.addEventListener("click", async () => {
        // TODO: 공통 modal 컴포넌트 도입 시 브라우저 confirm() 을 교체한다.
        if (!confirm(`'${material.originalFilename}' 자료를 삭제할까요?`)) return;
        try {
          await api(`/materials/${material.id}`, { method: "DELETE" });
          toast("자료를 삭제했습니다.");
          await loadMaterials($("course-select").value);
        } catch (error) {
          toast(error.message, "error");
        }
      });
      item.append(name, status, remove);
      list.appendChild(item);
    });
  }

  async function uploadMaterial() {
    const button = $("material-upload");
    const courseId = $("course-select").value;
    const file = $("material-file").files[0];
    if (!courseId) return toast("자료를 등록할 과목을 먼저 선택해주세요.", "error");
    if (!file) return toast("업로드할 파일(PDF/PPT)을 선택해주세요.", "error");
    const body = new FormData();
    body.append("file", file);
    body.append("courseId", courseId);
    body.append("sourceType", $("material-source").value);
    const week = $("material-week").value;
    if (week) body.append("week", week);
    setBusy(button, true, "업로드 중...");
    try {
      await api("/materials/upload", { method: "POST", body });
      $("material-file").value = "";
      $("material-week").value = "";
      toast("자료를 업로드했습니다. 인덱싱이 완료되면 번역 품질에 반영됩니다.");
      await loadMaterials(courseId);
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
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
      const liveKit = await api(`/sessions/${session.id}/professor-token`, {
        method: "POST",
      });
      state.session.liveKit = liveKit;
      await connectProfessor(liveKit);
      await loadQr(session.id);
      enterProfessorLive();
      toast("진행 중인 수업과 마이크 연결을 복구했습니다.");
      return true;
    } catch (error) {
      await disconnectRoom();
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
      if (state.room) await disconnectRoom();
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
    if (state.room !== room) return;
    const shouldEnable = !state.micPausedByUser;
    if (room.localParticipant.isMicrophoneEnabled !== shouldEnable) {
      await room.localParticipant.setMicrophoneEnabled(shouldEnable);
    }
    updateMicUi(shouldEnable);
  }

  async function connectProfessor(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({
      adaptiveStream: true,
      dynacast: true,
      // 교수 마이크는 사람이 듣는 통화가 아니라 STT 입력이다.
      // livekit-client 기본값(AGC/노이즈억제/voiceIsolation 전부 on)은 대화용이라
      // 자음의 고주파를 깎고 게인을 흔들어 전공 용어 인식률을 떨어뜨린다.
      audioCaptureDefaults: {
        autoGainControl: false,
        echoCancellation: false,
        noiseSuppression: false,
        voiceIsolation: false,
        channelCount: 1,
      },
      publishDefaults: {
        audioPreset: LivekitClient.AudioPresets.musicHighQuality,
        // DTX 는 무음 구간 전송을 멈춰 문장 첫 음절을 잘라먹고,
        // 워커 오디오 스트림의 시간축을 깨 segmentation 을 오작동시킨다.
        dtx: false,
        red: true,
        forceStereo: false,
      },
    });
    state.room = room;
    state.lastProfSequence = 0;
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      let data;
      try {
        data = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }
      // stt.partial(비신뢰 채널)과 stt.final(신뢰 채널)은 서로 순서가 보장되지 않는다.
      // 같은 노드에 덮어쓰면 텍스트가 과거로 되돌아가므로 확정/중간을 분리해 그린다.
      if (topic !== "stt") return;
      if (data.type === "stt.final") {
        if (typeof data.sequence === "number") {
          if (data.sequence <= state.lastProfSequence) return;
          state.lastProfSequence = data.sequence;
        }
        // 표시 전용: 직전 확정 발화를 목록으로 내리고 최신 칸을 비운다.
        archiveProfUtterance();
        $("prof-final").textContent = data.text || "";
        $("prof-partial").textContent = "";
        if (profScroller) profScroller.onAppend();
        startCaptionExpiry();
      } else if (data.type === "stt.partial") {
        $("prof-partial").textContent = data.text || "";
      }
    });
    room.on(LivekitClient.RoomEvent.Reconnecting, () => {
      if (state.room !== room) return;
      clearTimeout(state.connectionStatusTimer);
      setSessionStatus("재연결 중", "is-warn");
    });
    room.on(LivekitClient.RoomEvent.Reconnected, async () => {
      if (state.room !== room) return;
      setSessionStatus("다시 연결됨", "is-info");
      try {
        await syncProfessorMicrophone(room);
      } catch (error) {
        toast(`마이크 상태를 복구하지 못했습니다: ${error.message}`, "error");
      }
      state.connectionStatusTimer = setTimeout(() => {
        if (state.room === room) {
          setSessionStatus("수업 진행 중", "is-live");
        }
      }, 2000);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      if (state.room !== room) return;
      setSessionStatus("연결 끊김", "is-error");
      setMicBadge("연결 끊김", "is-error");
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
    $("live-session-code").textContent = state.session.id.slice(0, 3).toUpperCase();
    setSessionStatus("수업 진행 중", "is-live");
    updateMicUi(!state.micPausedByUser);
    resetProfTranscript();
    $("locale-count").textContent = `${state.session.targetLocales.length}개 언어`;
    $("lang-targets").textContent = state.session.targetLocales
      .map((code) => LOCALES.find((locale) => locale.code === code)?.name || code)
      .join(" · ");
    const firstMaterial = state.materials[0];
    $("material-row-name").textContent = firstMaterial
      ? firstMaterial.originalFilename
      : "등록된 강의 자료 없음";
    $("material-row-meta").textContent = state.materials.length
      ? [
          firstMaterial.sourceType === "major" ? "전공 자료" : "강의안",
          firstMaterial.week ? `${firstMaterial.week}주차` : null,
          `총 ${state.materials.length}개`,
        ].filter(Boolean).join(" · ")
      : "수업 준비 화면에서 자료를 업로드하세요";
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
      const base = worker ? labels[worker.status] || worker.status : "응답 대기";
      // 전공 용어집/lexicon/RAG 가 실제로 걸려 있는지 화면에서 바로 보이게 한다.
      // 이게 없으면 "자막이 이상하다"의 원인이 설정 누락인지 알 방법이 없다.
      const d = worker && worker.diagnostics;
      let suffix = "";
      if (d) {
        const warnings = [];
        if (!d.phraseList) warnings.push("전공용어 미적용");
        else if (!d.lexicon) warnings.push("lexicon 없음");
        if (d.rag === "off") warnings.push("RAG off");
        suffix = warnings.length
          ? ` · ⚠ ${warnings.join(", ")}`
          : ` · 용어 ${d.phraseList}개(${d.lexicon})`;
      }
      $("worker-status").textContent = base + suffix;
    } catch {
      $("worker-status").textContent = "확인 불가";
    }
  }

  async function endSession() {
    // TODO: 공통 modal 컴포넌트 도입 시 브라우저 confirm() 을 교체한다.
    if (state.endingSession || !state.session || !confirm("현재 수업을 종료할까요? 학생의 자막과 음성도 함께 종료됩니다.")) return;
    const button = $("end-session");
    const endingSessionId = state.session.id;
    state.endingSession = true;
    setBusy(button, true, "수업을 종료하고 있습니다...");
    try {
      await api(`/sessions/${endingSessionId}/end`, { method: "POST" });
      await disconnectRoom();
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
        // 회원 로그인 상태면 Student JWT 로 본인 식별. 게스트는 joinToken 만으로 입장.
        headers: state.studentToken ? { Authorization: `Bearer ${state.studentToken}` } : {},
        body: JSON.stringify({ joinToken, locale: state.selectedStudentLocale }),
      });
      state.studentSessionId = payload.sessionId;
      state.captionHistory = [];
      await connectStudent(liveKit);
      $("student-join").classList.add("hidden");
      $("student-live").classList.remove("hidden");
      const locale = LOCALES.find((item) => item.code === state.selectedStudentLocale);
      $("student-locale-label").textContent = `${locale.name} · ${locale.native}`;
      $("slide-course-title").textContent = $("joined-session-label").textContent.replace(/^•\s*/, "") || "실시간 강의";
      toast("강의실에 입장했습니다.");
    } catch (error) {
      await disconnectRoom();
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  // 학생은 자기 언어의 TTS 트랙 하나만 구독한다.
  // autoSubscribe 기본값(true)으로 두면 교수 마이크 원음까지 구독되고, LiveKit SDK 가
  // 구독된 오디오를 자동 재생하기 때문에 한국어 원음이 번역 음성과 겹쳐 들린다.
  // TrackSubscribed 의 trackName 필터는 수동 attach 만 막을 뿐 자동 재생을 막지 못한다.
  function studentTtsTrackName() {
    return `tts.${state.selectedStudentLocale}`;
  }

  function syncStudentSubscription(publication) {
    if (!publication || publication.kind !== LivekitClient.Track.Kind.Audio) return;
    const wanted = publication.trackName === studentTtsTrackName();
    if (Boolean(publication.isSubscribed) === wanted) return;
    publication.setSubscribed(wanted);
  }

  // 입장 전에 이미 올라와 있던 트랙은 TrackPublished 가 오지 않으므로 직접 훑는다.
  function syncStudentSubscriptions(room) {
    room.remoteParticipants.forEach((participant) => {
      participant.trackPublications.forEach(syncStudentSubscription);
    });
  }

  // ── 오디오 재생 잠금 해제 (태블릿/모바일 autoplay 차단 대응) ────────
  // 모바일 브라우저는 사용자 제스처 전까지 audio.play() 를 조용히 거부한다.
  // 예전에는 "화면을 눌러 허용해주세요" 토스트만 있고 그 탭을 받는 코드가 없어
  // 학생이 영구 무음에 갇혔다 — 실제 태블릿에서 관측된 장애.
  function showAudioUnlock() {
    $("audio-unlock").classList.remove("hidden");
    $("audio-status").textContent = "소리가 꺼져 있습니다 — 화면의 버튼을 탭하세요";
  }

  function hideAudioUnlock() {
    $("audio-unlock").classList.add("hidden");
  }

  async function unlockStudentAudio() {
    try {
      // startAudio() 가 브라우저 재생 권한을 얻고, iOS 의 백그라운드 복귀
      // 자동복구 훅(SDK 내장)도 이 호출로 등록된다.
      if (state.room) await state.room.startAudio();
      await $("translation-audio").play();
      hideAudioUnlock();
      $("audio-status").textContent = "번역 음성 재생 중";
    } catch {
      // 아직 제스처로 인정 안 된 경우 — 버튼을 유지해 다음 탭을 기다린다.
      showAudioUnlock();
    }
  }

  async function connectStudent(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({ adaptiveStream: true });
    state.room = room;
    room.on(LivekitClient.RoomEvent.TrackPublished, syncStudentSubscription);
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication) => {
      if (track.kind !== LivekitClient.Track.Kind.Audio || publication.trackName !== `tts.${state.selectedStudentLocale}`) return;
      const audio = $("translation-audio");
      track.attach(audio);
      audio.play().then(() => {
        hideAudioUnlock();
        $("audio-status").textContent = "번역 음성 재생 중";
      }).catch(() => showAudioUnlock());
    });
    // SDK 가 재생 차단을 감지하면 알려준다 (탭 전환·백그라운드 복귀 포함).
    room.on(LivekitClient.RoomEvent.AudioPlaybackStatusChanged, () => {
      if (state.room !== room) return;
      if (room.canPlaybackAudio) hideAudioUnlock();
      else showAudioUnlock();
    });
    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
      track.detach();
      $("audio-status").textContent = "다음 번역 음성을 기다리는 중";
    });
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      handleStudentData(payload, topic);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      stopCaptionExpiry();
      $("audio-status").textContent = "연결이 종료되었습니다";
      toast("강의실 연결이 종료되었습니다.");
    });
    state.lastCaptionSequence = 0;
    await room.connect(liveKit.liveKitUrl, liveKit.token, { autoSubscribe: false });
    syncStudentSubscriptions(room);
  }

  function handleStudentData(payload, topic) {
    let data;
    try {
      data = JSON.parse(new TextDecoder().decode(payload));
    } catch {
      return;
    }
    // locale 필터는 자막에만 적용한다. audio-status 등 세션 단위 이벤트에는
    // locale 이 없거나 의미가 달라, 토픽별로 분기해야 한다.
    if (topic === "caption") {
      if (data.locale !== state.selectedStudentLocale) return;
      if (data.type === "caption.partial") return;
      // 서버가 sequence 를 보내는데 예전엔 클라이언트가 한 번도 읽지 않았다.
      // 늦게 도착한 패킷이 최신 자막을 덮어쓰지 않도록 막는다.
      if (typeof data.sequence === "number") {
        if (data.sequence <= state.lastCaptionSequence) return;
        state.lastCaptionSequence = data.sequence;
      }
      addCaption(data.text, data.sourceKo, { isFallback: Boolean(data.isFallback) });
      return;
    }
    if (topic === "audio-status") {
      if (data.locale && data.locale !== state.selectedStudentLocale) return;
      // 서버 페이로드의 키는 status 가 아니라 type 이다(models.audio_status_payload).
      // 예전 코드는 data.status 를 읽어 항상 기본 문구만 표시했다.
      const labels = {
        "audio.started": "번역 음성 준비 중",
        "audio.completed": "다음 발화를 기다리는 중",
        "audio.failed": "이 문장은 음성 없이 자막만 제공됩니다",
      };
      $("audio-status").textContent = labels[data.type] || "번역 음성 처리 중";
    }
  }

  // 발화 단위 목록 UX: 최근 30개 발화를 5분 동안 유지한다 (무제한 누적 금지 —
  // 초과분은 오래된 것부터 제거, TTL 경과분은 기존 방식대로 주기 정리).
  const CAPTION_TTL_MS = 5 * 60 * 1000;
  const CAPTION_MAX_ITEMS = 30;

  function addCaption(text, sourceKo, options) {
    if (!text) return;
    const isFallback = Boolean(options && options.isFallback);
    // 화면에서는 곧 사라지지만 기록 패널에서 스크롤백할 수 있게 보관한다.
    state.captionHistory.push({ text, sourceKo, isFallback, at: Date.now() });
    if (state.captionHistory.length > CAPTION_HISTORY_MAX) state.captionHistory.shift();
    if ($("history-dialog").open) renderHistoryItems(state.captionHistory);
    const captions = $("captions");
    const empty = captions.querySelector(".caption-empty");
    if (empty) empty.remove();

    const item = document.createElement("div");
    item.className = isFallback ? "caption fallback" : "caption";
    item.dataset.expiresAt = String(Date.now() + CAPTION_TTL_MS);

    // 발화 메타: 화자(현재는 교수 단일 화자) + 타임스탬프
    const meta = document.createElement("div");
    meta.className = "caption-meta";
    const speaker = document.createElement("span");
    speaker.className = "speaker";
    speaker.textContent = "교수";
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
    meta.append(speaker, time);
    item.appendChild(meta);

    // 번역문이 주 자막이다. 한국어 원문은 STT 오인식이 그대로 노출되는 자리라
    // 보조 크기로 낮춘다(styles.css 의 .translated / .source 참조).
    const content = document.createElement("span");
    content.className = "translated";
    content.textContent = text;
    item.appendChild(content);

    if (isFallback) {
      const notice = document.createElement("span");
      notice.className = "fallback-note";
      notice.textContent = "번역 실패 — 원문 표시";
      item.appendChild(notice);
    } else if (sourceKo) {
      const source = document.createElement("span");
      source.className = "source";
      source.textContent = sourceKo;
      item.appendChild(source);
    }

    captions.appendChild(item);
    while (captions.children.length > CAPTION_MAX_ITEMS) captions.firstElementChild.remove();
    if (studentScroller) studentScroller.onAppend();
    startCaptionExpiry();
  }

  // 학생 자막(#captions)과 교수 원문 목록(#professor-transcript)을 함께 정리한다.
  // 교수 목록의 최신 발화(.latest)는 expiresAt 이 없어 정리 대상에서 자연히 빠진다.
  function sweepExpiredCaptions(container, now) {
    if (!container) return 0;
    // 마지막 한 줄은 남긴다 — 발화 사이에 화면이 통째로 비면 장애로 오인된다.
    while (container.children.length > 1) {
      const first = container.firstElementChild;
      const expiresAt = Number(first.dataset.expiresAt || 0);
      if (!expiresAt || expiresAt > now) break;
      first.remove();
    }
    return [...container.children].filter((el) => el.dataset.expiresAt).length;
  }

  function startCaptionExpiry() {
    if (state.captionExpiryTimer) return;
    state.captionExpiryTimer = setInterval(() => {
      const now = Date.now();
      const remaining =
        sweepExpiredCaptions($("captions"), now) +
        sweepExpiredCaptions($("professor-transcript"), now);
      if (remaining === 0) stopCaptionExpiry();
    }, 1000);
  }

  function stopCaptionExpiry() {
    if (!state.captionExpiryTimer) return;
    clearInterval(state.captionExpiryTimer);
    state.captionExpiryTimer = null;
  }

  const PROF_PLACEHOLDER = "교수님의 음성을 기다리고 있습니다.";

  // 교수 화면 원문 발화 목록 (표시 전용) — 이 화면에는 번역문 데이터가 없으므로
  // stt.final 원문만 발화 단위로 쌓는다. 최신 발화는 .latest 칸(prof-final)이 담당하고,
  // 확정 발화가 새로 오면 직전 발화를 시각적으로 낮은 명도의 목록 항목으로 내린다.
  function archiveProfUtterance() {
    const list = $("professor-transcript");
    const latest = list.querySelector(".prof-utterance.latest");
    const text = $("prof-final").textContent.trim();
    if (!latest || !text || text === PROF_PLACEHOLDER) return;
    const item = document.createElement("div");
    item.className = "prof-utterance";
    item.dataset.expiresAt = String(Date.now() + CAPTION_TTL_MS);
    const meta = document.createElement("div");
    meta.className = "caption-meta";
    const speaker = document.createElement("span");
    speaker.className = "speaker";
    speaker.textContent = "교수";
    const time = document.createElement("time");
    time.textContent = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
    meta.append(speaker, time);
    const content = document.createElement("span");
    content.textContent = text;
    item.append(meta, content);
    list.insertBefore(item, latest);
    // .latest 는 항상 마지막 요소라 오래된 것부터 지우는 아래 루프에 걸리지 않는다.
    while (list.children.length > CAPTION_MAX_ITEMS) list.firstElementChild.remove();
  }

  function resetProfTranscript() {
    const list = $("professor-transcript");
    [...list.querySelectorAll(".prof-utterance:not(.latest)")].forEach((el) => el.remove());
    $("prof-final").textContent = PROF_PLACEHOLDER;
    $("prof-partial").textContent = "";
    if (profScroller) profScroller.reset();
  }

  async function leaveStudentSession() {
    await disconnectRoom();
    stopCaptionExpiry();
    renderRecentHistory(state.captionHistory);
    state.lastCaptionSequence = 0;
    state.studentSessionId = "";
    state.captionHistory = [];
    if ($("history-dialog").open) $("history-dialog").close();
    hideAudioUnlock();
    $("student-live").classList.add("hidden");
    $("student-join").classList.remove("hidden");
    $("captions").innerHTML = '<div class="caption-empty">교수님의 발화를 기다리고 있습니다.<br>번역 자막이 이곳에 표시됩니다.</div>';
    if (studentScroller) studentScroller.reset();
    // 다음 입장을 위해 자막 패널 표시 상태를 초기화한다 (표시 전용).
    setTranscriptState("open");
    syncAutoscrollButton(true);
  }

  // ── 자막 기록(스크롤백) ──────────────────────────────────────────────
  // 수업(세션) 단위 열람: 다이얼로그 상단의 셀렉트에서 지난 수업을 고르면
  // 그 수업의 전체 자막을 DB 에서 페이지 단위로 끝까지 읽어온다.
  // 교수는 한국어 확정 자막, 학생은 (한국어 + 본인 선택 언어)를 본다.
  const TRANSCRIPT_PAGE_LIMIT = 500;

  function showHistoryDialog() {
    const dialog = $("history-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function setHistoryLoading() {
    $("history-list").innerHTML = '<p class="history-empty">자막을 불러오는 중...</p>';
  }

  /** afterSequence 커서로 전체 세그먼트를 읽는다 — 한 수업이 500개를 넘어도 잘리지 않게. */
  async function fetchAllTranscriptPages(fetchPage) {
    const all = [];
    let afterSequence;
    for (;;) {
      const batch = await fetchPage(afterSequence);
      all.push(...batch);
      if (batch.length < TRANSCRIPT_PAGE_LIMIT) return all;
      afterSequence = batch[batch.length - 1].sequence;
    }
  }

  function formatSessionOption(row) {
    const started = row.startedAt ? new Date(row.startedAt) : null;
    const when = started
      ? `${started.toLocaleDateString("ko-KR")} ${started.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}`
      : "";
    const name = row.courseName || "수업";
    const suffix = row.status === "active" ? " · 진행 중" : "";
    return `${name} · ${when}${suffix}`;
  }

  function populateHistorySelect(options, selectedId) {
    const select = $("history-session-select");
    select.innerHTML = "";
    if (!options.length) {
      select.classList.add("hidden");
      return null;
    }
    options.forEach((opt) => {
      const el = document.createElement("option");
      el.value = opt.sessionId;
      el.textContent = opt.label;
      if (opt.locale) el.dataset.locale = opt.locale;
      select.appendChild(el);
    });
    select.classList.remove("hidden");
    const chosen = selectedId && options.some((o) => o.sessionId === selectedId)
      ? selectedId
      : options[0].sessionId;
    select.value = chosen;
    return chosen;
  }

  // ── 학생 ──
  async function openHistory() {
    state.historyRole = "student";
    showHistoryDialog();
    setHistoryLoading();

    const options = [];
    if (state.studentToken) {
      // 로그인 학생: 참여했던 수업 목록 (서버가 최신순으로 준다).
      try {
        const mine = await api("/students/me/sessions", {
          auth: false,
          headers: { Authorization: `Bearer ${state.studentToken}` },
        });
        mine.forEach((row) => options.push({
          sessionId: row.sessionId,
          label: formatSessionOption(row),
          locale: row.locale,
        }));
      } catch {
        // 목록 실패 시 아래의 현재 세션 폴백만 남는다.
      }
    }
    if (state.studentSessionId && !options.some((o) => o.sessionId === state.studentSessionId)) {
      // 게스트(QR) 또는 목록 조회 실패: 현재 접속 중인 수업만.
      options.unshift({
        sessionId: state.studentSessionId,
        label: "현재 수업",
        locale: state.selectedStudentLocale,
      });
    }

    const chosen = populateHistorySelect(options, state.studentSessionId);
    if (!chosen) {
      renderHistoryItems(state.captionHistory);
      return;
    }
    await loadStudentHistory(chosen);
  }

  async function loadStudentHistory(sessionId) {
    setHistoryLoading();
    const select = $("history-session-select");
    const optionLocale =
      select.selectedOptions[0] && select.selectedOptions[0].dataset.locale;
    const locale = optionLocale || state.selectedStudentLocale;
    const joinToken = $("join-token").value.trim();
    try {
      const rows = await fetchAllTranscriptPages((afterSequence) =>
        api(`/sessions/${sessionId}/transcripts/query`, {
          method: "POST",
          auth: false,
          headers: state.studentToken
            ? { Authorization: `Bearer ${state.studentToken}` }
            : {},
          body: JSON.stringify({
            limit: TRANSCRIPT_PAGE_LIMIT,
            ...(afterSequence !== undefined ? { afterSequence } : {}),
            ...(state.studentToken ? {} : { joinToken }),
          }),
        }),
      );
      renderHistoryItems(rows.map((row) => {
        const entry = (row.translations || {})[locale] || null;
        return {
          text: entry ? entry.text : row.textKo,
          sourceKo: row.textKo,
          isFallback: entry ? Boolean(entry.isFallback) : true,
          at: new Date(row.createdAt).getTime(),
        };
      }));
    } catch (error) {
      // 서버 조회 실패: 현재 세션이면 이 기기에서 수신한 로컬 기록으로 폴백.
      if (sessionId === state.studentSessionId && state.captionHistory.length) {
        renderHistoryItems(state.captionHistory);
        return;
      }
      renderHistoryItems([]);
      toast(`자막 기록을 불러오지 못했습니다: ${error.message}`, "error");
    }
  }

  // ── 교수 ──
  // 진행 중 수업이 없어도 지난 수업 목록에서 골라 전체 자막을 볼 수 있다.
  async function openProfessorHistory() {
    state.historyRole = "professor";
    showHistoryDialog();
    setHistoryLoading();

    let options = [];
    try {
      const rows = await api("/sessions");
      options = rows.map((row) => ({
        sessionId: row.id,
        label: formatSessionOption({
          // 서버가 course relation 을 함께 실어 준다 (leftJoinAndSelect).
          courseName: row.course ? row.course.name : "수업",
          startedAt: row.startedAt,
          status: row.status,
        }),
      }));
    } catch (error) {
      renderHistoryItems([]);
      toast(`수업 목록을 불러오지 못했습니다: ${error.message}`, "error");
      return;
    }

    const chosen = populateHistorySelect(
      options,
      state.session ? state.session.id : null,
    );
    if (!chosen) {
      renderHistoryItems([]);
      return;
    }
    await loadProfessorHistory(chosen);
  }

  async function loadProfessorHistory(sessionId) {
    setHistoryLoading();
    try {
      const rows = await fetchAllTranscriptPages((afterSequence) =>
        api(
          `/sessions/${sessionId}/transcripts?limit=${TRANSCRIPT_PAGE_LIMIT}` +
            (afterSequence !== undefined ? `&afterSequence=${afterSequence}` : ""),
        ),
      );
      renderHistoryItems(rows.map((row) => ({
        text: row.textKo,
        sourceKo: row.rawTextKo && row.rawTextKo !== row.textKo ? row.rawTextKo : null,
        isFallback: false,
        at: new Date(row.createdAt).getTime(),
      })));
    } catch (error) {
      renderHistoryItems([]);
      toast(`자막 기록을 불러오지 못했습니다: ${error.message}`, "error");
    }
  }

  // 학생 대시보드 "최근 번역 기록" — 방금 나온 수업의 자막을 남겨 복습을 돕는다.
  function renderRecentHistory(items) {
    const panel = $("recent-history");
    if (!panel || !items.length) return;
    panel.innerHTML = "";
    const recent = items.slice(-5).reverse();
    recent.forEach((row) => {
      const line = document.createElement("div");
      line.className = "recent-item";
      const text = document.createElement("p");
      text.textContent = row.text;
      const meta = document.createElement("small");
      meta.textContent = new Date(row.at).toLocaleString("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      line.append(text, meta);
      panel.appendChild(line);
    });
    const note = document.createElement("small");
    note.textContent = `최근 수업 자막 ${items.length}건 중 ${recent.length}건 표시`;
    panel.appendChild(note);
  }

  function renderHistoryItems(items) {
    const list = $("history-list");
    list.innerHTML = "";
    if (!items.length) {
      list.innerHTML = '<p class="history-empty">아직 저장된 자막이 없습니다.</p>';
      return;
    }
    items.forEach((row) => {
      const item = document.createElement("div");
      item.className = row.isFallback ? "history-item fallback" : "history-item";
      const content = document.createElement("span");
      content.className = "translated";
      content.textContent = row.text;
      item.appendChild(content);
      if (!row.isFallback && row.sourceKo && row.sourceKo !== row.text) {
        const source = document.createElement("span");
        source.className = "source";
        source.textContent = row.sourceKo;
        item.appendChild(source);
      }
      const time = document.createElement("time");
      time.textContent = new Date(row.at).toLocaleTimeString("ko-KR", {
        hour: "2-digit",
        minute: "2-digit",
      });
      item.appendChild(time);
      list.appendChild(item);
    });
    list.scrollTop = list.scrollHeight;
  }

  // ── 학생 프로필(DB) 연동 ─────────────────────────────────────────────
  function updateStudentProfileUi() {
    const logged = Boolean(state.studentProfile);
    $("student-name").textContent = logged ? state.studentProfile.name : "UniVoice 학생";
    $("student-greeting-name").textContent = logged ? state.studentProfile.name : "학생";
    $("student-login-status").textContent = logged
      ? state.studentProfile.email
      : "게스트 입장";
    $("student-auth").textContent = logged ? "로그아웃" : "로그인";
  }

  function selectStudentLocale(code) {
    const input = document.querySelector(`input[name="student-locale"][value="${code}"]`);
    if (!input || input.checked) return;
    input.checked = true;
    input.dispatchEvent(new Event("change"));
  }

  async function loadStudentProfile() {
    if (!state.studentToken) return updateStudentProfileUi();
    const payload = getJoinData(state.studentToken);
    if (!payload?.sub) return studentLogout();
    try {
      state.studentProfile = await api(`/students/${payload.sub}`, {
        auth: false,
        headers: { Authorization: `Bearer ${state.studentToken}` },
      });
    } catch {
      // 토큰 만료 등 — 게스트 상태로 되돌린다.
      return studentLogout();
    }
    if (state.studentProfile.preferredLocale) {
      selectStudentLocale(state.studentProfile.preferredLocale);
    }
    updateStudentProfileUi();
  }

  function studentLogout() {
    state.studentToken = "";
    state.studentProfile = null;
    sessionStorage.removeItem("univoice.studentToken");
    updateStudentProfileUi();
  }

  async function studentLogin(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    setBusy(button, true, "로그인 중...");
    try {
      const result = await api("/auth/student/login", {
        method: "POST",
        auth: false,
        body: JSON.stringify({
          email: $("student-email").value.trim(),
          password: $("student-password").value,
        }),
      });
      state.studentToken = result.accessToken;
      sessionStorage.setItem("univoice.studentToken", result.accessToken);
      await loadStudentProfile();
      $("student-login-dialog").close();
      toast("로그인되었습니다. 프로필과 선호 언어가 연동됩니다.");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  function savePreferredLocale(locale) {
    if (!state.studentToken || !state.studentProfile) return;
    if (state.studentProfile.preferredLocale === locale) return;
    state.studentProfile.preferredLocale = locale;
    api(`/students/${state.studentProfile.id}`, {
      method: "PATCH",
      auth: false,
      headers: { Authorization: `Bearer ${state.studentToken}` },
      body: JSON.stringify({ preferredLocale: locale }),
    }).catch(() => undefined);
  }

  async function disconnectRoom() {
    if (!state.room) return;
    const room = state.room;
    state.room = null;
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
    void disconnectRoom();
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
    studentScroller = createCaptionScroller("captions", "captions-jump-latest", syncAutoscrollButton);
    profScroller = createCaptionScroller("professor-transcript", "prof-jump-latest");

    // 자막 패널 접기/펼치기/최소화/닫기 (표시 전용 상태 전환)
    $("transcript-toggle").addEventListener("click", () => {
      setTranscriptState(transcriptViewState === "closed" ? "open" : "closed");
    });
    $("transcript-close").addEventListener("click", () => setTranscriptState("closed"));
    $("transcript-reopen").addEventListener("click", () => setTranscriptState("open"));
    $("transcript-minimize").addEventListener("click", () => setTranscriptState("minimized"));
    $("transcript-expand").addEventListener("click", () => setTranscriptState("open"));
    // 명시적 자동 스크롤 toggle — 기존 scroller.pinned 상태를 그대로 재사용한다.
    $("autoscroll-toggle").addEventListener("click", () => {
      if (studentScroller.pinned) studentScroller.unpin();
      else studentScroller.toLatest();
    });
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
    $("course-select").addEventListener("change", () => {
      updateRecoveryControls();
      loadMaterials($("course-select").value).catch(() => undefined);
    });
    $("material-upload").addEventListener("click", () => {
      uploadMaterial().catch((error) => toast(error.message, "error"));
    });
    $("material-link").addEventListener("click", () => {
      if (!state.materials.length) return toast("이 과목에 등록된 자료가 없습니다.");
      toast(state.materials.map((material) => material.originalFilename).join(", "));
    });
    $("show-history").addEventListener("click", () => {
      openHistory().catch(() => undefined);
    });
    // 대시보드 "전체 보기" — 기존 자막 기록 다이얼로그(openHistory)를 그대로 연다.
    $("recent-history-all").addEventListener("click", () => {
      openHistory().catch(() => undefined);
    });
    $("prof-history").addEventListener("click", () => {
      openProfessorHistory().catch(() => undefined);
    });
    $("close-history").addEventListener("click", () => $("history-dialog").close());
    $("audio-unlock").addEventListener("click", () => {
      unlockStudentAudio().catch(() => undefined);
    });
    // 버튼 밖 아무 곳을 탭해도 그 제스처로 재생을 재시도한다 (안내 문구와 동작 일치).
    document.addEventListener("pointerdown", () => {
      if (!$("audio-unlock").classList.contains("hidden")) {
        unlockStudentAudio().catch(() => undefined);
      }
    });
    $("history-session-select").addEventListener("change", (event) => {
      const sessionId = event.target.value;
      if (!sessionId) return;
      const load = state.historyRole === "professor" ? loadProfessorHistory : loadStudentHistory;
      load(sessionId).catch(() => undefined);
    });
    $("student-auth").addEventListener("click", () => {
      if (state.studentProfile) {
        studentLogout();
        toast("로그아웃되었습니다.");
        return;
      }
      const dialog = $("student-login-dialog");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });
    $("close-student-login").addEventListener("click", () => $("student-login-dialog").close());
    $("student-login-form").addEventListener("submit", studentLogin);
    $("end-session").addEventListener("click", endSession);
    $("logout").addEventListener("click", logout);
    $("join-session").addEventListener("click", joinStudentSession);
    $("leave-session").addEventListener("click", leaveStudentSession);
    $("mic-pause").addEventListener("click", async () => {
      if (!state.room) return;
      const room = state.room;
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
      if (!state.room) return;
      const room = state.room;
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
      if (state.room) {
        const room = state.room;
        state.room = null;
        room.disconnect();
      }
    });

    updateStudentProfileUi();
    if (state.studentToken) {
      loadStudentProfile().catch(() => undefined);
    }
    if (state.accessToken && state.mode === "professor") {
      initializeProfessor().catch(() => logout());
    }
  }

  // 표시 전용 개발 훅: ?uvdev 쿼리로 열면 자막 UI(개수 제한·TTL·자동 스크롤)를
  // 실제 세션 없이 수동 주입해 검증할 수 있다. 프로덕션 동작에는 관여하지 않는다.
  // initialize() 안의 showMode() 가 replaceState 로 쿼리를 지우므로 먼저 읽는다.
  const devMode = new URLSearchParams(location.search).has("uvdev");

  initialize();

  if (devMode) {
    window.__uvdev = { addCaption };
  }
})();
