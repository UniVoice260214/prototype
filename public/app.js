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

  // UI strings for the student screens, keyed by interface language. Korean
  // stays hard-coded in index.html and doubles as the fallback for any
  // locale/key this dictionary doesn't cover, so foreign students never see
  // a blank string -- worst case they see Korean instead of a missing key.
  const STUDENT_I18N = {
    "en-US": {
      "nav.home": "Home", "nav.qrShortcut": "Scan QR", "nav.settings": "Settings", "nav.contact": "Help",
      "profile.name": "UniVoice Student", "profile.guest": "Guest access",
      "today.title": "Today's Lecture", "today.empty": "Scan a QR code to join a lecture.",
      "today.emptyHint": "Once your join token is verified, you'll connect to the live class.",
      "today.connected": "Connected via QR — ready to join today's lecture",
      "today.invalid": "This join link isn't valid. Please scan the QR code again.",
      "today.ended": "This lecture has already ended.",
      "recent.title": "Recent Translations", "recent.empty": "No saved translations yet.",
      "recent.emptyHint": "They'll show up here after you join a class.",
      "settings.title": "Interpretation / Display Settings", "settings.lectureLang": "Lecture language",
      "settings.displayLang": "Display language", "settings.accessibility": "Accessibility",
      "token.empty": "Scan the QR code to connect automatically.", "token.auto": "Connected automatically via QR",
      "token.invalid": "Couldn't verify this link. Please scan the QR code again.",
      "token.manualSummary": "Enter join token manually",
      "token.manualPlaceholder": "Filled in automatically when you scan the QR code.",
      "token.manualLabel": "Join token",
      "token.manualHint": "Not needed if you joined via QR. Don't share this token with anyone.",
      "locales.legend": "Choose translation language", "caption.previewTitle": "Caption preview",
      "caption.previewKo": "Live Korean speech will be translated into your language.",
      "join.button": "Join live lecture", "live.subtitle2": "UniVoice translation mode",
      "live.title": "Live lecture translation",
      "live.subtitle": "Follow the translated captions alongside the professor's materials.",
      "live.audioWaiting": "Waiting to connect translated audio", "live.audioPlaying": "Playing translated audio",
      "live.audioNextWaiting": "Waiting for the next translated audio", "live.audioQueued": "Preparing translated audio",
      "live.audioCompleted": "Waiting for the next speech", "live.audioFailed": "Couldn't generate audio",
      "live.audioDisconnected": "Connection closed", "live.leave": "Leave",
      "live.captionEmpty": "Waiting for the professor to speak.",
      "localeDialog.title": "Change translation language",
      "localeDialog.desc": "Switching updates the interpreted audio and captions immediately.",
      "captions.enlarge": "Enlarge captions", "captions.shrink": "Reset caption size",
      "err.noJoinToken": "A join token is required. Please scan the QR code again.",
      "err.noLocale": "Please choose a translation language.", "err.invalidToken": "This isn't a valid join token.",
      "err.localeNotAvailable": "This lecture doesn't offer that language. Please choose another.",
      "msg.joined": "You've joined the lecture.", "msg.autoplayBlocked": "Tap the screen once to allow audio playback.",
      "msg.roomClosed": "The classroom connection has ended.", "msg.localeChanged": "Translation language changed.",
      "greeting.title": "Hello, {name}", "greeting.student": "Student",
      "greeting.subtitle": "Check today's lecture and join the class with live translation.",
      "today.badge": "Live translation available", "join.enter": "Join", "join.connecting": "Connecting to the classroom...",
      "recent.viewAll": "View all", "recent.note": "Showing {shown} of {total} captions from your last class",
      "lang.korean": "Korean", "settings.changeLocale": "Change translation language",
      "auth.login": "Log in", "auth.logout": "Log out", "auth.loggingIn": "Logging in...", "auth.title": "Student login",
      "auth.desc": "Logging in saves your name and preferred language to your profile.",
      "auth.email": "Email", "auth.password": "Password", "profile.edit": "Edit profile",
      "msg.loggedIn": "Logged in. Your profile and preferred language are now synced.", "msg.loggedOut": "Logged out.",
      "live.localeFixed": "Rejoin to change", "live.history": "Caption history",
      "live.audioProcessing": "Processing translated audio", "live.captionEmptyHint": "Translated captions will appear here.",
      "slide.empty": "No lecture materials to show", "slide.emptyHint": "Shared lecture materials will appear in this area.",
      "captions.title": "Live captions", "captions.autoscrollOn": "Auto-scroll on", "captions.autoscrollOff": "Auto-scroll off",
      "captions.jumpLatest": "↓ Jump to latest", "captions.reopen": "Show captions",
      "caption.speaker": "Professor", "caption.fallback": "Translation failed — showing original",
      "audio.unlock": "🔊 Tap to enable sound", "audio.muted": "Sound is off — tap the button on screen",
    },
    "ja-JP": {
      "nav.home": "ホーム", "nav.qrShortcut": "QRで入室", "nav.settings": "設定", "nav.contact": "お問い合わせ",
      "profile.name": "UniVoice 学生", "profile.guest": "ゲスト入室",
      "today.title": "本日の講義", "today.empty": "QRコードをスキャンして講義に参加してください。",
      "today.emptyHint": "入室トークンを確認するとライブ授業に接続されます。",
      "today.connected": "QRで接続済み — 本日の講義にすぐ参加できます",
      "today.invalid": "入室情報が正しくありません。QRコードを再度スキャンしてください。",
      "today.ended": "この講義はすでに終了しました。",
      "recent.title": "最近の翻訳履歴", "recent.empty": "保存された翻訳履歴はまだありません。",
      "recent.emptyHint": "授業に参加するとここに表示されます。",
      "settings.title": "通訳・表示設定", "settings.lectureLang": "講義の言語",
      "settings.displayLang": "画面表示言語", "settings.accessibility": "アクセシビリティ",
      "token.empty": "QRコードをスキャンすると自動で接続されます。", "token.auto": "QRで自動接続されました",
      "token.invalid": "リンクを確認できませんでした。QRコードを再度スキャンしてください。",
      "token.manualSummary": "入室トークンを直接入力",
      "token.manualPlaceholder": "QRコードでアクセスすると自動的に入力されます。",
      "token.manualLabel": "入室トークン",
      "token.manualHint": "QRで入室した場合は不要です。トークンは他人と共有しないでください。",
      "locales.legend": "翻訳言語を選択", "caption.previewTitle": "字幕プレビュー",
      "caption.previewKo": "韓国語の音声はリアルタイムで選択した言語に翻訳されます。",
      "join.button": "ライブ講義に参加", "live.subtitle2": "UniVoice 翻訳モード",
      "live.title": "ライブ講義翻訳",
      "live.subtitle": "教授の講義資料と一緒に翻訳字幕を確認してください。",
      "live.audioWaiting": "翻訳音声の接続を待っています", "live.audioPlaying": "翻訳音声を再生中",
      "live.audioNextWaiting": "次の翻訳音声を待っています", "live.audioQueued": "翻訳音声を準備中",
      "live.audioCompleted": "次の発話を待っています", "live.audioFailed": "音声の生成に失敗しました",
      "live.audioDisconnected": "接続が終了しました", "live.leave": "退出",
      "live.captionEmpty": "教授の発話を待っています。",
      "localeDialog.title": "翻訳言語を変更",
      "localeDialog.desc": "切り替えると通訳音声と字幕がすぐに変わります。",
      "captions.enlarge": "字幕を拡大", "captions.shrink": "字幕サイズを戻す",
      "err.noJoinToken": "入室トークンが必要です。QRコードから再度アクセスしてください。",
      "err.noLocale": "翻訳言語を選択してください。", "err.invalidToken": "有効な入室トークンではありません。",
      "err.localeNotAvailable": "この講義では選択した言語を提供していません。別の言語を選んでください。",
      "msg.joined": "講義に参加しました。", "msg.autoplayBlocked": "画面を一度タップすると音声再生が許可されます。",
      "msg.roomClosed": "教室との接続が終了しました。", "msg.localeChanged": "翻訳言語を変更しました。",
      "greeting.title": "こんにちは、{name}さん", "greeting.student": "学生",
      "greeting.subtitle": "本日の講義を確認し、リアルタイム翻訳と一緒に授業に参加しましょう。",
      "today.badge": "リアルタイム翻訳対応", "join.enter": "入室", "join.connecting": "教室に接続中...",
      "recent.viewAll": "すべて見る", "recent.note": "直近の授業の字幕 {total}件中 {shown}件を表示",
      "lang.korean": "韓国語", "settings.changeLocale": "翻訳言語を変更",
      "auth.login": "ログイン", "auth.logout": "ログアウト", "auth.loggingIn": "ログイン中...", "auth.title": "学生ログイン",
      "auth.desc": "ログインすると名前と希望言語がプロフィールに保存されます。",
      "auth.email": "メールアドレス", "auth.password": "パスワード", "profile.edit": "プロフィール編集",
      "msg.loggedIn": "ログインしました。プロフィールと希望言語が連携されます。", "msg.loggedOut": "ログアウトしました。",
      "live.localeFixed": "再入室で変更", "live.history": "字幕履歴",
      "live.audioProcessing": "翻訳音声を処理中", "live.captionEmptyHint": "翻訳字幕がここに表示されます。",
      "slide.empty": "表示する講義資料がありません", "slide.emptyHint": "講義資料が共有されるとこの領域に表示されます。",
      "captions.title": "リアルタイム字幕", "captions.autoscrollOn": "自動スクロール オン", "captions.autoscrollOff": "自動スクロール オフ",
      "captions.jumpLatest": "↓ 最新の字幕へ", "captions.reopen": "字幕を開く",
      "caption.speaker": "教授", "caption.fallback": "翻訳失敗 — 原文を表示",
      "audio.unlock": "🔊 タップして音声をオン", "audio.muted": "音声がオフです — 画面のボタンをタップしてください",
    },
    "zh-CN": {
      "nav.home": "首页", "nav.qrShortcut": "扫码入场", "nav.settings": "设置", "nav.contact": "联系我们",
      "profile.name": "UniVoice 学生", "profile.guest": "访客身份",
      "today.title": "今日课程", "today.empty": "请扫描二维码加入课程。",
      "today.emptyHint": "验证入场令牌后即可连接到实时课堂。",
      "today.connected": "已通过二维码连接 — 可立即加入今日课程",
      "today.invalid": "入场信息无效，请重新扫描二维码。", "today.ended": "本次课程已结束。",
      "recent.title": "最近的翻译记录", "recent.empty": "暂无已保存的翻译记录。",
      "recent.emptyHint": "加入课程后可在此查看。",
      "settings.title": "口译/显示设置", "settings.lectureLang": "授课语言",
      "settings.displayLang": "显示语言", "settings.accessibility": "无障碍设置",
      "token.empty": "扫描二维码即可自动连接。", "token.auto": "已通过二维码自动连接",
      "token.invalid": "无法验证该链接，请重新扫描二维码。",
      "token.manualSummary": "手动输入入场令牌", "token.manualPlaceholder": "扫描二维码后将自动填写。",
      "token.manualLabel": "入场令牌", "token.manualHint": "通过二维码入场则无需填写。请勿与他人分享此令牌。",
      "locales.legend": "选择翻译语言", "caption.previewTitle": "字幕预览",
      "caption.previewKo": "实时韩语语音将被翻译成您选择的语言。",
      "join.button": "加入实时课程", "live.subtitle2": "UniVoice 翻译模式",
      "live.title": "实时课程翻译", "live.subtitle": "结合教授的讲义资料查看翻译字幕。",
      "live.audioWaiting": "正在等待连接翻译音频", "live.audioPlaying": "正在播放翻译音频",
      "live.audioNextWaiting": "正在等待下一段翻译音频", "live.audioQueued": "正在准备翻译音频",
      "live.audioCompleted": "正在等待下一次发言", "live.audioFailed": "语音生成失败",
      "live.audioDisconnected": "连接已断开", "live.leave": "离开",
      "live.captionEmpty": "正在等待教授发言。",
      "localeDialog.title": "更改翻译语言", "localeDialog.desc": "切换后口译音频和字幕将立即更新。",
      "captions.enlarge": "放大字幕", "captions.shrink": "恢复字幕大小",
      "err.noJoinToken": "需要入场令牌，请重新扫描二维码。", "err.noLocale": "请选择翻译语言。",
      "err.invalidToken": "不是有效的入场令牌。",
      "err.localeNotAvailable": "本课程未提供该语言，请选择其他语言。",
      "msg.joined": "已加入课程。", "msg.autoplayBlocked": "请点按屏幕一次以允许播放音频。",
      "msg.roomClosed": "课堂连接已结束。", "msg.localeChanged": "已更改翻译语言。",
      "greeting.title": "你好，{name}", "greeting.student": "同学",
      "greeting.subtitle": "查看今日课程，借助实时翻译参与课堂。",
      "today.badge": "支持实时翻译", "join.enter": "入场", "join.connecting": "正在连接课堂...",
      "recent.viewAll": "查看全部", "recent.note": "显示最近课程字幕 {total} 条中的 {shown} 条",
      "lang.korean": "韩语", "settings.changeLocale": "更改翻译语言",
      "auth.login": "登录", "auth.logout": "退出登录", "auth.loggingIn": "登录中...", "auth.title": "学生登录",
      "auth.desc": "登录后，您的姓名和偏好语言将保存到个人资料。",
      "auth.email": "邮箱", "auth.password": "密码", "profile.edit": "编辑个人信息",
      "msg.loggedIn": "已登录。个人资料和偏好语言已同步。", "msg.loggedOut": "已退出登录。",
      "live.localeFixed": "重新入场可更改", "live.history": "字幕记录",
      "live.audioProcessing": "正在处理翻译音频", "live.captionEmptyHint": "翻译字幕将显示在这里。",
      "slide.empty": "暂无可显示的讲义资料", "slide.emptyHint": "讲义资料共享后将显示在此区域。",
      "captions.title": "实时字幕", "captions.autoscrollOn": "自动滚动 开", "captions.autoscrollOff": "自动滚动 关",
      "captions.jumpLatest": "↓ 跳到最新字幕", "captions.reopen": "打开字幕",
      "caption.speaker": "教授", "caption.fallback": "翻译失败 — 显示原文",
      "audio.unlock": "🔊 点按开启声音", "audio.muted": "声音已关闭 — 请点按屏幕上的按钮",
    },
    "zh-TW": {
      "nav.home": "首頁", "nav.qrShortcut": "掃碼入場", "nav.settings": "設定", "nav.contact": "聯絡我們",
      "profile.name": "UniVoice 學生", "profile.guest": "訪客身分",
      "today.title": "今日課程", "today.empty": "請掃描 QR code 加入課程。",
      "today.emptyHint": "驗證入場權杖後即可連接到即時課堂。",
      "today.connected": "已透過 QR code 連接 — 可立即加入今日課程",
      "today.invalid": "入場資訊無效，請重新掃描 QR code。", "today.ended": "本次課程已結束。",
      "recent.title": "最近的翻譯紀錄", "recent.empty": "尚無已儲存的翻譯紀錄。",
      "recent.emptyHint": "加入課程後可在此查看。",
      "settings.title": "口譯/顯示設定", "settings.lectureLang": "授課語言",
      "settings.displayLang": "顯示語言", "settings.accessibility": "無障礙設定",
      "token.empty": "掃描 QR code 即可自動連接。", "token.auto": "已透過 QR code 自動連接",
      "token.invalid": "無法驗證此連結，請重新掃描 QR code。",
      "token.manualSummary": "手動輸入入場權杖", "token.manualPlaceholder": "掃描 QR code 後將自動填入。",
      "token.manualLabel": "入場權杖", "token.manualHint": "透過 QR code 入場則不需要。請勿與他人分享此權杖。",
      "locales.legend": "選擇翻譯語言", "caption.previewTitle": "字幕預覽",
      "caption.previewKo": "即時韓語語音將翻譯成您選擇的語言。",
      "join.button": "加入即時課程", "live.subtitle2": "UniVoice 翻譯模式",
      "live.title": "即時課程翻譯", "live.subtitle": "搭配教授的講義資料查看翻譯字幕。",
      "live.audioWaiting": "正在等待連接翻譯音訊", "live.audioPlaying": "正在播放翻譯音訊",
      "live.audioNextWaiting": "正在等待下一段翻譯音訊", "live.audioQueued": "正在準備翻譯音訊",
      "live.audioCompleted": "正在等待下一次發言", "live.audioFailed": "語音產生失敗",
      "live.audioDisconnected": "連線已中斷", "live.leave": "離開",
      "live.captionEmpty": "正在等待教授發言。",
      "localeDialog.title": "變更翻譯語言", "localeDialog.desc": "切換後口譯音訊與字幕會立即更新。",
      "captions.enlarge": "放大字幕", "captions.shrink": "還原字幕大小",
      "err.noJoinToken": "需要入場權杖，請重新掃描 QR code。", "err.noLocale": "請選擇翻譯語言。",
      "err.invalidToken": "不是有效的入場權杖。",
      "err.localeNotAvailable": "本課程未提供該語言，請選擇其他語言。",
      "msg.joined": "已加入課程。", "msg.autoplayBlocked": "請點一下畫面以允許播放音訊。",
      "msg.roomClosed": "課堂連線已結束。", "msg.localeChanged": "已變更翻譯語言。",
      "greeting.title": "你好，{name}", "greeting.student": "同學",
      "greeting.subtitle": "查看今日課程，搭配即時翻譯參與課堂。",
      "today.badge": "支援即時翻譯", "join.enter": "入場", "join.connecting": "正在連線至教室...",
      "recent.viewAll": "查看全部", "recent.note": "顯示最近課程字幕 {total} 則中的 {shown} 則",
      "lang.korean": "韓語", "settings.changeLocale": "變更翻譯語言",
      "auth.login": "登入", "auth.logout": "登出", "auth.loggingIn": "登入中...", "auth.title": "學生登入",
      "auth.desc": "登入後，您的姓名與偏好語言會儲存至個人資料。",
      "auth.email": "電子郵件", "auth.password": "密碼", "profile.edit": "編輯個人資料",
      "msg.loggedIn": "已登入。個人資料與偏好語言已同步。", "msg.loggedOut": "已登出。",
      "live.localeFixed": "重新入場可變更", "live.history": "字幕紀錄",
      "live.audioProcessing": "正在處理翻譯音訊", "live.captionEmptyHint": "翻譯字幕會顯示在這裡。",
      "slide.empty": "沒有可顯示的講義資料", "slide.emptyHint": "講義資料分享後會顯示在此區域。",
      "captions.title": "即時字幕", "captions.autoscrollOn": "自動捲動 開", "captions.autoscrollOff": "自動捲動 關",
      "captions.jumpLatest": "↓ 跳至最新字幕", "captions.reopen": "開啟字幕",
      "caption.speaker": "教授", "caption.fallback": "翻譯失敗 — 顯示原文",
      "audio.unlock": "🔊 點一下開啟聲音", "audio.muted": "聲音已關閉 — 請點一下畫面上的按鈕",
    },
    "vi-VN": {
      "nav.home": "Trang chủ", "nav.qrShortcut": "Quét QR", "nav.settings": "Cài đặt", "nav.contact": "Liên hệ",
      "profile.name": "Sinh viên UniVoice", "profile.guest": "Truy cập khách",
      "today.title": "Buổi học hôm nay", "today.empty": "Quét mã QR để vào buổi học.",
      "today.emptyHint": "Sau khi xác thực token, bạn sẽ được kết nối vào lớp học trực tiếp.",
      "today.connected": "Đã kết nối qua QR — sẵn sàng vào buổi học hôm nay",
      "today.invalid": "Liên kết vào lớp không hợp lệ. Vui lòng quét lại mã QR.",
      "today.ended": "Buổi học này đã kết thúc.",
      "recent.title": "Lịch sử bản dịch gần đây", "recent.empty": "Chưa có bản dịch nào được lưu.",
      "recent.emptyHint": "Bản dịch sẽ hiện ở đây sau khi bạn tham gia lớp học.",
      "settings.title": "Cài đặt phiên dịch / hiển thị", "settings.lectureLang": "Ngôn ngữ giảng dạy",
      "settings.displayLang": "Ngôn ngữ hiển thị", "settings.accessibility": "Trợ năng",
      "token.empty": "Quét mã QR để tự động kết nối.", "token.auto": "Đã tự động kết nối qua QR",
      "token.invalid": "Không thể xác thực liên kết này. Vui lòng quét lại mã QR.",
      "token.manualSummary": "Nhập token vào lớp thủ công",
      "token.manualPlaceholder": "Sẽ tự động điền khi bạn quét mã QR.",
      "token.manualLabel": "Token vào lớp",
      "token.manualHint": "Không cần nếu bạn vào bằng QR. Không chia sẻ token này với người khác.",
      "locales.legend": "Chọn ngôn ngữ dịch", "caption.previewTitle": "Xem trước phụ đề",
      "caption.previewKo": "Giọng nói tiếng Hàn trực tiếp sẽ được dịch sang ngôn ngữ bạn chọn.",
      "join.button": "Vào lớp học trực tiếp", "live.subtitle2": "Chế độ dịch UniVoice",
      "live.title": "Dịch bài giảng trực tiếp",
      "live.subtitle": "Theo dõi phụ đề dịch cùng với tài liệu của giảng viên.",
      "live.audioWaiting": "Đang chờ kết nối âm thanh dịch", "live.audioPlaying": "Đang phát âm thanh dịch",
      "live.audioNextWaiting": "Đang chờ đoạn âm thanh dịch tiếp theo", "live.audioQueued": "Đang chuẩn bị âm thanh dịch",
      "live.audioCompleted": "Đang chờ lượt phát biểu tiếp theo", "live.audioFailed": "Tạo âm thanh không thành công",
      "live.audioDisconnected": "Kết nối đã đóng", "live.leave": "Rời lớp",
      "live.captionEmpty": "Đang chờ giảng viên phát biểu.",
      "localeDialog.title": "Đổi ngôn ngữ dịch",
      "localeDialog.desc": "Khi chuyển đổi, âm thanh phiên dịch và phụ đề sẽ cập nhật ngay lập tức.",
      "captions.enlarge": "Phóng to phụ đề", "captions.shrink": "Khôi phục cỡ phụ đề",
      "err.noJoinToken": "Cần có token vào lớp. Vui lòng quét lại mã QR.",
      "err.noLocale": "Vui lòng chọn ngôn ngữ dịch.", "err.invalidToken": "Đây không phải token vào lớp hợp lệ.",
      "err.localeNotAvailable": "Buổi học này không hỗ trợ ngôn ngữ đó. Vui lòng chọn ngôn ngữ khác.",
      "msg.joined": "Bạn đã vào lớp học.", "msg.autoplayBlocked": "Chạm vào màn hình một lần để cho phép phát âm thanh.",
      "msg.roomClosed": "Kết nối lớp học đã kết thúc.", "msg.localeChanged": "Đã đổi ngôn ngữ dịch.",
      "greeting.title": "Xin chào, {name}", "greeting.student": "Sinh viên",
      "greeting.subtitle": "Xem buổi học hôm nay và tham gia lớp cùng bản dịch trực tiếp.",
      "today.badge": "Hỗ trợ dịch trực tiếp", "join.enter": "Vào lớp", "join.connecting": "Đang kết nối vào lớp học...",
      "recent.viewAll": "Xem tất cả", "recent.note": "Hiển thị {shown}/{total} phụ đề của buổi học gần nhất",
      "lang.korean": "Tiếng Hàn", "settings.changeLocale": "Đổi ngôn ngữ dịch",
      "auth.login": "Đăng nhập", "auth.logout": "Đăng xuất", "auth.loggingIn": "Đang đăng nhập...", "auth.title": "Đăng nhập sinh viên",
      "auth.desc": "Khi đăng nhập, tên và ngôn ngữ ưa thích sẽ được lưu vào hồ sơ của bạn.",
      "auth.email": "Email", "auth.password": "Mật khẩu", "profile.edit": "Chỉnh sửa hồ sơ",
      "msg.loggedIn": "Đã đăng nhập. Hồ sơ và ngôn ngữ ưa thích đã được đồng bộ.", "msg.loggedOut": "Đã đăng xuất.",
      "live.localeFixed": "Vào lại để đổi", "live.history": "Lịch sử phụ đề",
      "live.audioProcessing": "Đang xử lý âm thanh dịch", "live.captionEmptyHint": "Phụ đề dịch sẽ hiện ở đây.",
      "slide.empty": "Chưa có tài liệu bài giảng để hiển thị", "slide.emptyHint": "Tài liệu được chia sẻ sẽ hiển thị ở khu vực này.",
      "captions.title": "Phụ đề trực tiếp", "captions.autoscrollOn": "Tự cuộn: bật", "captions.autoscrollOff": "Tự cuộn: tắt",
      "captions.jumpLatest": "↓ Đến phụ đề mới nhất", "captions.reopen": "Mở phụ đề",
      "caption.speaker": "Giảng viên", "caption.fallback": "Dịch thất bại — hiển thị bản gốc",
      "audio.unlock": "🔊 Chạm để bật âm thanh", "audio.muted": "Âm thanh đang tắt — hãy chạm vào nút trên màn hình",
    },
    "mn-MN": {
      "nav.home": "Нүүр", "nav.qrShortcut": "QR уншуулах", "nav.settings": "Тохиргоо", "nav.contact": "Холбоо барих",
      "profile.name": "UniVoice оюутан", "profile.guest": "Зочноор нэвтэрсэн",
      "today.title": "Өнөөдрийн хичээл", "today.empty": "Хичээлд орохын тулд QR кодыг уншуулна уу.",
      "today.emptyHint": "Нэвтрэх токеныг баталгаажуулмагц бодит цагийн хичээлд холбогдоно.",
      "today.connected": "QR-ээр холбогдсон — өнөөдрийн хичээлд шууд нэвтэрч болно",
      "today.invalid": "Нэвтрэх мэдээлэл буруу байна. QR кодыг дахин уншуулна уу.",
      "today.ended": "Энэ хичээл аль хэдийн дууссан байна.",
      "recent.title": "Сүүлийн орчуулгын түүх", "recent.empty": "Хадгалагдсан орчуулга одоогоор алга байна.",
      "recent.emptyHint": "Хичээлд нэвтэрсний дараа энд харагдана.",
      "settings.title": "Орчуулга/дэлгэцийн тохиргоо", "settings.lectureLang": "Хичээлийн хэл",
      "settings.displayLang": "Дэлгэцэд харуулах хэл", "settings.accessibility": "Хүртээмж",
      "token.empty": "QR кодыг уншуулбал автоматаар холбогдоно.", "token.auto": "QR-ээр автоматаар холбогдлоо",
      "token.invalid": "Энэ холбоосыг баталгаажуулж чадсангүй. QR кодыг дахин уншуулна уу.",
      "token.manualSummary": "Нэвтрэх токеныг гараар оруулах",
      "token.manualPlaceholder": "QR кодоор нэвтрэхэд автоматаар бөглөгдөнө.",
      "token.manualLabel": "Нэвтрэх токен",
      "token.manualHint": "QR-ээр нэвтэрсэн бол шаардлагагүй. Энэ токеныг бусадтай бүү хуваалцаарай.",
      "locales.legend": "Орчуулах хэлээ сонгоно уу", "caption.previewTitle": "Хадмал урьдчилан харах",
      "caption.previewKo": "Бодит цагийн солонгос яриаг таны сонгосон хэл рүү орчуулна.",
      "join.button": "Шууд хичээлд нэвтрэх", "live.subtitle2": "UniVoice орчуулгын горим",
      "live.title": "Шууд хичээлийн орчуулга",
      "live.subtitle": "Багшийн материалын хамт орчуулсан хадмал бичгийг харна уу.",
      "live.audioWaiting": "Орчуулгын дуу холбогдохыг хүлээж байна", "live.audioPlaying": "Орчуулгын дуу тоглож байна",
      "live.audioNextWaiting": "Дараагийн орчуулгын дууг хүлээж байна", "live.audioQueued": "Орчуулгын дууг бэлтгэж байна",
      "live.audioCompleted": "Дараагийн яриаг хүлээж байна", "live.audioFailed": "Дуу үүсгэж чадсангүй",
      "live.audioDisconnected": "Холболт тасарлаа", "live.leave": "Гарах",
      "live.captionEmpty": "Багшийн ярихыг хүлээж байна.",
      "localeDialog.title": "Орчуулах хэл солих",
      "localeDialog.desc": "Соливол орчуулгын дуу болон хадмал шууд шинэчлэгдэнэ.",
      "captions.enlarge": "Хадмалыг томруулах", "captions.shrink": "Хадмалын хэмжээг буцаах",
      "err.noJoinToken": "Нэвтрэх токен шаардлагатай. QR кодыг дахин уншуулна уу.",
      "err.noLocale": "Орчуулах хэлээ сонгоно уу.", "err.invalidToken": "Энэ хүчинтэй нэвтрэх токен биш байна.",
      "err.localeNotAvailable": "Энэ хичээл тухайн хэлийг санал болгодоггүй. Өөр хэл сонгоно уу.",
      "msg.joined": "Хичээлд нэвтэрлээ.", "msg.autoplayBlocked": "Дууг тоглуулахыг зөвшөөрөхийн тулд дэлгэцийг нэг товшино уу.",
      "msg.roomClosed": "Ангийн холболт дууслаа.", "msg.localeChanged": "Орчуулах хэлийг өөрчиллөө.",
      "greeting.title": "Сайн байна уу, {name}", "greeting.student": "Оюутан",
      "greeting.subtitle": "Өнөөдрийн хичээлээ шалгаад бодит цагийн орчуулгатайгаар хичээлд оролцоорой.",
      "today.badge": "Бодит цагийн орчуулгатай", "join.enter": "Нэвтрэх", "join.connecting": "Ангид холбогдож байна...",
      "recent.viewAll": "Бүгдийг харах", "recent.note": "Сүүлийн хичээлийн {total} хадмалаас {shown}-ийг харуулж байна",
      "lang.korean": "Солонгос хэл", "settings.changeLocale": "Орчуулах хэл солих",
      "auth.login": "Нэвтрэх", "auth.logout": "Гарах", "auth.loggingIn": "Нэвтэрч байна...", "auth.title": "Оюутны нэвтрэлт",
      "auth.desc": "Нэвтэрсний дараа таны нэр болон сонгосон хэл профайлд хадгалагдана.",
      "auth.email": "Имэйл", "auth.password": "Нууц үг", "profile.edit": "Профайл засах",
      "msg.loggedIn": "Нэвтэрлээ. Профайл болон сонгосон хэл холбогдлоо.", "msg.loggedOut": "Гарлаа.",
      "live.localeFixed": "Дахин нэвтэрч солино", "live.history": "Хадмалын түүх",
      "live.audioProcessing": "Орчуулгын дууг боловсруулж байна", "live.captionEmptyHint": "Орчуулсан хадмал энд харагдана.",
      "slide.empty": "Харуулах хичээлийн материал алга", "slide.emptyHint": "Хичээлийн материал хуваалцмагц энд харагдана.",
      "captions.title": "Бодит цагийн хадмал", "captions.autoscrollOn": "Автомат гүйлгэлт асаалттай", "captions.autoscrollOff": "Автомат гүйлгэлт унтраалттай",
      "captions.jumpLatest": "↓ Хамгийн сүүлийн хадмал руу", "captions.reopen": "Хадмал нээх",
      "caption.speaker": "Багш", "caption.fallback": "Орчуулга амжилтгүй — эх текстийг харуулж байна",
      "audio.unlock": "🔊 Дуу асаахын тулд товшино уу", "audio.muted": "Дуу унтраалттай байна — дэлгэц дээрх товчийг товшино уу",
    },
    "uk-UA": {
      "nav.home": "Головна", "nav.qrShortcut": "Сканувати QR", "nav.settings": "Налаштування", "nav.contact": "Зв'язок",
      "profile.name": "Студент UniVoice", "profile.guest": "Гостьовий вхід",
      "today.title": "Сьогоднішня лекція", "today.empty": "Відскануйте QR-код, щоб приєднатися до лекції.",
      "today.emptyHint": "Після підтвердження токена ви підключитеся до заняття в реальному часі.",
      "today.connected": "Підключено через QR — можна одразу приєднатися до сьогоднішньої лекції",
      "today.invalid": "Це посилання для входу недійсне. Відскануйте QR-код ще раз.",
      "today.ended": "Ця лекція вже завершилася.",
      "recent.title": "Останні переклади", "recent.empty": "Збережених перекладів поки немає.",
      "recent.emptyHint": "Вони з'являться тут після приєднання до заняття.",
      "settings.title": "Налаштування перекладу / відображення", "settings.lectureLang": "Мова лекції",
      "settings.displayLang": "Мова відображення", "settings.accessibility": "Доступність",
      "token.empty": "Відскануйте QR-код для автоматичного підключення.", "token.auto": "Підключено автоматично через QR",
      "token.invalid": "Не вдалося підтвердити це посилання. Відскануйте QR-код ще раз.",
      "token.manualSummary": "Ввести токен входу вручну",
      "token.manualPlaceholder": "Заповнюється автоматично при скануванні QR-коду.",
      "token.manualLabel": "Токен входу",
      "token.manualHint": "Не потрібно, якщо ви увійшли через QR. Не діліться цим токеном з іншими.",
      "locales.legend": "Оберіть мову перекладу", "caption.previewTitle": "Попередній перегляд субтитрів",
      "caption.previewKo": "Корейська мова наживо перекладатиметься на обрану вами мову.",
      "join.button": "Приєднатися до лекції наживо", "live.subtitle2": "Режим перекладу UniVoice",
      "live.title": "Переклад лекції наживо",
      "live.subtitle": "Переглядайте перекладені субтитри разом із матеріалами викладача.",
      "live.audioWaiting": "Очікування підключення перекладеного аудіо", "live.audioPlaying": "Відтворення перекладеного аудіо",
      "live.audioNextWaiting": "Очікування наступного перекладеного аудіо", "live.audioQueued": "Підготовка перекладеного аудіо",
      "live.audioCompleted": "Очікування наступного виступу", "live.audioFailed": "Не вдалося створити аудіо",
      "live.audioDisconnected": "З'єднання завершено", "live.leave": "Вийти",
      "live.captionEmpty": "Очікування виступу викладача.",
      "localeDialog.title": "Змінити мову перекладу",
      "localeDialog.desc": "Після перемикання перекладене аудіо та субтитри одразу оновляться.",
      "captions.enlarge": "Збільшити субтитри", "captions.shrink": "Повернути звичайний розмір",
      "err.noJoinToken": "Потрібен токен входу. Відскануйте QR-код ще раз.",
      "err.noLocale": "Будь ласка, оберіть мову перекладу.", "err.invalidToken": "Це недійсний токен входу.",
      "err.localeNotAvailable": "Ця лекція не пропонує цю мову. Оберіть іншу.",
      "msg.joined": "Ви приєдналися до лекції.", "msg.autoplayBlocked": "Торкніться екрана один раз, щоб дозволити відтворення звуку.",
      "msg.roomClosed": "З'єднання з аудиторією завершено.", "msg.localeChanged": "Мову перекладу змінено.",
      "greeting.title": "Вітаємо, {name}", "greeting.student": "Студенте",
      "greeting.subtitle": "Перегляньте сьогоднішню лекцію та приєднуйтеся до заняття з перекладом наживо.",
      "today.badge": "Доступний переклад наживо", "join.enter": "Увійти", "join.connecting": "Підключення до аудиторії...",
      "recent.viewAll": "Переглянути все", "recent.note": "Показано {shown} із {total} субтитрів останнього заняття",
      "lang.korean": "Корейська", "settings.changeLocale": "Змінити мову перекладу",
      "auth.login": "Увійти", "auth.logout": "Вийти", "auth.loggingIn": "Вхід...", "auth.title": "Вхід для студентів",
      "auth.desc": "Після входу ваше ім'я та бажана мова зберігаються в профілі.",
      "auth.email": "Електронна пошта", "auth.password": "Пароль", "profile.edit": "Редагувати профіль",
      "msg.loggedIn": "Ви увійшли. Профіль і бажану мову синхронізовано.", "msg.loggedOut": "Ви вийшли.",
      "live.localeFixed": "Змінити після повторного входу", "live.history": "Історія субтитрів",
      "live.audioProcessing": "Обробка перекладеного аудіо", "live.captionEmptyHint": "Перекладені субтитри з'являться тут.",
      "slide.empty": "Немає матеріалів лекції для показу", "slide.emptyHint": "Надані матеріали лекції з'являться в цій області.",
      "captions.title": "Субтитри наживо", "captions.autoscrollOn": "Автопрокрутка увімкнена", "captions.autoscrollOff": "Автопрокрутка вимкнена",
      "captions.jumpLatest": "↓ До останніх субтитрів", "captions.reopen": "Показати субтитри",
      "caption.speaker": "Викладач", "caption.fallback": "Переклад не вдався — показано оригінал",
      "audio.unlock": "🔊 Торкніться, щоб увімкнути звук", "audio.muted": "Звук вимкнено — торкніться кнопки на екрані",
    },
  };

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
    uiLocale: "en-US",
    activeSessions: [],
    micPausedByUser: false,
    endingSession: false,
    autoJoinToken: "",
    joinSessionId: "",
    joinTokenInvalid: false,
    sessionPublicInfo: null,
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

  // ---- i18n helpers (student screens only; professor UI stays Korean per CLAUDE.md) ----
  function translate(key) {
    return STUDENT_I18N[state.uiLocale]?.[key];
  }

  function t(key, fallbackKo) {
    return translate(key) ?? fallbackKo;
  }

  function detectInitialLocale() {
    const candidates = (navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language])
      .filter(Boolean)
      .map((lang) => lang.toLowerCase());
    for (const lang of candidates) {
      const primary = lang.split("-")[0];
      if (primary === "zh") {
        if (lang.includes("tw") || lang.includes("hant") || lang.includes("hk")) return "zh-TW";
        return "zh-CN";
      }
      const match = LOCALES.find((locale) => locale.code.toLowerCase().startsWith(primary));
      if (match) return match.code;
    }
    return "en-US";
  }

  // data-i18n 표기가 있는 학생 화면 요소만 교체한다. 표기가 없으면 한국어 그대로.
  // 학생 로그인 다이얼로그는 #student-app 밖(top-level)에 있어 범위에 따로 넣는다.
  // 자막 기록 다이얼로그는 교수와 공유하므로 제외(교수 UI 는 한국어 유지).
  const STUDENT_I18N_SCOPE = "#student-app [data-i18n], #student-login-dialog [data-i18n]";
  const STUDENT_I18N_PLACEHOLDER_SCOPE = "#student-app [data-i18n-placeholder], #student-login-dialog [data-i18n-placeholder]";

  function applyStudentI18n() {
    document.querySelectorAll(STUDENT_I18N_SCOPE).forEach((el) => {
      const value = translate(el.dataset.i18n);
      if (value != null) el.textContent = value;
    });
    document.querySelectorAll(STUDENT_I18N_PLACEHOLDER_SCOPE).forEach((el) => {
      const value = translate(el.dataset.i18nPlaceholder);
      if (value != null) el.setAttribute("placeholder", value);
    });
    // JS 가 직접 그리는 문구는 data-i18n 을 못 타므로 여기서 다시 그린다.
    refreshJoinedSessionLabel();
    updateStudentProfileUi();
    if (studentScroller) syncAutoscrollButton(studentScroller.pinned);
  }

  // 과목명·오류 상태가 섞인 문구라 data-i18n 텍스트 교체로는 표현할 수 없어
  // 직접 다시 그린다.
  function refreshJoinedSessionLabel() {
    const label = $("joined-session-label");
    if (!state.autoJoinToken) {
      label.textContent = t("today.empty", "QR을 스캔해 강의에 입장하세요.");
      return;
    }
    if (state.joinTokenInvalid) {
      label.textContent = t("today.invalid", "입장 정보가 올바르지 않습니다.");
      return;
    }
    const info = state.sessionPublicInfo;
    if (info?.status === "ended") {
      label.textContent = t("today.ended", "이 강의는 이미 종료되었습니다.");
    } else if (info?.courseName) {
      label.textContent = `${info.courseName} · ${t("today.connected", "QR로 연결된 오늘의 실시간 강의")}`;
    } else {
      label.textContent = t("today.connected", "• QR로 연결된 오늘의 실시간 강의");
    }
  }

  function setUiLocale(code) {
    state.uiLocale = code;
    applyStudentI18n();
  }

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
    button.textContent = pinned
      ? t("captions.autoscrollOn", "자동 스크롤 켬")
      : t("captions.autoscrollOff", "자동 스크롤 끔");
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

  // Combined "영어(English)" style label used everywhere a locale is shown.
  function localeLabel(locale) {
    return `${locale.name}(${locale.native})`;
  }

  function renderProfessorLocales() {
    $("professor-locales").innerHTML = LOCALES.map((locale, index) => `
      <label class="locale-option">
        <input type="checkbox" value="${locale.code}" ${index < 3 ? "checked" : ""}>
        <span>${localeLabel(locale)}</span>
      </label>
    `).join("");
  }

  function renderStudentLocales(allowedCodes) {
    const allowed = allowedCodes && allowedCodes.length
      ? LOCALES.filter((locale) => allowedCodes.includes(locale.code))
      : LOCALES;
    if (!allowed.some((locale) => locale.code === state.selectedStudentLocale)) {
      state.selectedStudentLocale = allowed[0]?.code || state.selectedStudentLocale;
    }
    $("student-locales").innerHTML = allowed.map((locale) => `
      <label class="locale-option">
        <input type="radio" name="student-locale" value="${locale.code}" ${locale.code === state.selectedStudentLocale ? "checked" : ""}>
        <span><b>${locale.flag}</b><span>${localeLabel(locale)}</span></span>
      </label>
    `).join("");
    document.querySelectorAll('input[name="student-locale"]').forEach((input) => {
      input.addEventListener("change", () => {
        const locale = LOCALES.find((item) => item.code === input.value);
        state.selectedStudentLocale = input.value;
        $("selected-language").textContent = `${locale.name} · ${locale.native}`;
        setUiLocale(locale.code);
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

  // The demo-only professor/student mode toggle stays reachable everywhere
  // except mid-class, where an accidental tap would blow away the live view.
  function setModeSwitchVisible(visible) {
    $("switch-mode").classList.toggle("hidden", !visible);
  }

  function getJoinData(token) {
    try {
      const payloadPart = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(payloadPart))));
    } catch {
      return null;
    }
  }

  function getActiveJoinToken() {
    const manual = $("join-token").value.trim();
    return manual || state.autoJoinToken;
  }

  // 과목에 지정된 전공 (Course.major). 수업 중 이 전공의 RAG 만 검색된다는 걸 교수가 바로 보게 한다.
  const MAJOR_LABELS = { ai: "인공지능", hss: "인문사회", bme: "바이오의생명공학" };

  async function loadCourses() {
    const courses = await api("/courses");
    const select = $("course-select");
    select.innerHTML = courses.length
      ? courses.map((course) => {
          const major = course.major ? ` · ${MAJOR_LABELS[course.major] || course.major}` : "";
          return `<option value="${course.id}">${escapeHtml(course.name)}${escapeHtml(major)}</option>`;
        }).join("")
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
    setModeSwitchVisible(false);
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
        // 워커 진단값은 설정이 아니라 preflight 결과다: ready | off | unreachable | no-index
        // ("on" 은 구버전 워커 호환). 켜 놓고도 안 도는 경우를 여기서 바로 드러낸다.
        if (d.rag && d.rag !== "ready" && d.rag !== "on") {
          const ragWarnings = { off: "RAG off", unreachable: "RAG 연결 안 됨", "no-index": "RAG 인덱스 없음" };
          warnings.push(ragWarnings[d.rag] || `RAG ${d.rag}`);
        }
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
      setSessionStatus("수업 종료", "is-info");
      await disconnectRoom();
      clearSessionTimers();
      clearSavedSession();
      state.activeSessions = state.activeSessions.filter((session) => session.id !== endingSessionId);
      state.session = null;
      state.joinUrl = "";
      state.micPausedByUser = false;
      $("professor-live").classList.add("hidden");
      $("professor-setup").classList.remove("hidden");
      setModeSwitchVisible(true);
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

  async function fetchSessionPublicInfo(sessionId) {
    try {
      state.sessionPublicInfo = await api(`/sessions/${sessionId}/public`, { auth: false });
    } catch {
      state.sessionPublicInfo = null;
    }
    return state.sessionPublicInfo;
  }

  function applyJoinTokenState(payload) {
    state.joinTokenInvalid = !payload?.sessionId;
    refreshJoinedSessionLabel();
  }

  async function joinStudentSession() {
    const button = $("join-session");
    const joinToken = getActiveJoinToken();
    const localeInput = document.querySelector('input[name="student-locale"]:checked');
    if (!joinToken) return toast(t("err.noJoinToken", "입장 토큰이 필요합니다. QR 링크로 다시 접속해주세요."), "error");
    if (!localeInput) return toast(t("err.noLocale", "번역 언어를 선택해주세요."), "error");
    const payload = getJoinData(joinToken);
    if (!payload?.sessionId) return toast(t("err.invalidToken", "올바른 입장 토큰이 아닙니다."), "error");
    state.selectedStudentLocale = localeInput.value;
    setBusy(button, true, t("join.connecting", "강의실에 연결 중..."));
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
      setModeSwitchVisible(false);
      updateStudentLocaleLabel();
      $("slide-course-title").textContent = state.sessionPublicInfo?.courseName
        || $("joined-session-label").textContent.replace(/^•\s*/, "")
        || "실시간 강의";
      toast(t("msg.joined", "강의실에 입장했습니다."));
    } catch (error) {
      await disconnectRoom();
      toast(error.message, "error");
    } finally {
      setBusy(button, false);
    }
  }

  function updateStudentLocaleLabel() {
    const locale = LOCALES.find((item) => item.code === state.selectedStudentLocale);
    if (!locale) return;
    $("student-locale-label").textContent = `${locale.name} · ${locale.native}`;
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
    $("audio-status").textContent = t("audio.muted", "소리가 꺼져 있습니다 — 화면의 버튼을 탭하세요");
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
      $("audio-status").textContent = t("live.audioPlaying", "번역 음성 재생 중");
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
        $("audio-status").textContent = t("live.audioPlaying", "번역 음성 재생 중");
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
      $("audio-status").textContent = t("live.audioNextWaiting", "다음 번역 음성을 기다리는 중");
    });
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      handleStudentData(payload, topic);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      stopCaptionExpiry();
      $("audio-status").textContent = t("live.audioDisconnected", "연결이 종료되었습니다");
      toast(t("msg.roomClosed", "강의실 연결이 종료되었습니다."));
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
        "audio.started": t("live.audioQueued", "번역 음성 준비 중"),
        "audio.completed": t("live.audioCompleted", "다음 발화를 기다리는 중"),
        "audio.failed": t("live.audioFailed", "이 문장은 음성 없이 자막만 제공됩니다"),
      };
      $("audio-status").textContent = labels[data.type] || t("live.audioProcessing", "번역 음성 처리 중");
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
    speaker.textContent = t("caption.speaker", "교수");
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
      notice.textContent = t("caption.fallback", "번역 실패 — 원문 표시");
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
    setModeSwitchVisible(true);
    // 사전 문자열은 고정 리터럴이라 innerHTML 에 넣어도 안전하다.
    $("captions").innerHTML = `<div class="caption-empty">${t("live.captionEmpty", "교수님의 발화를 기다리고 있습니다.")}<br>${t("live.captionEmptyHint", "번역 자막이 이곳에 표시됩니다.")}</div>`;
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
    note.textContent = t("recent.note", "최근 수업 자막 {total}건 중 {shown}건 표시")
      .replace("{total}", String(items.length))
      .replace("{shown}", String(recent.length));
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
    $("student-name").textContent = logged ? state.studentProfile.name : t("profile.name", "UniVoice 학생");
    $("student-greeting").textContent = t("greeting.title", "안녕하세요, {name}님")
      .replace("{name}", logged ? state.studentProfile.name : t("greeting.student", "학생"));
    $("student-login-status").textContent = logged
      ? state.studentProfile.email
      : t("profile.guest", "게스트 입장");
    $("student-auth").textContent = logged ? t("auth.logout", "로그아웃") : t("auth.login", "로그인");
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
    setBusy(button, true, t("auth.loggingIn", "로그인 중..."));
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
      toast(t("msg.loggedIn", "로그인되었습니다. 프로필과 선호 언어가 연동됩니다."));
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
    setModeSwitchVisible(true);
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
    renderProfessorLocales();
    renderStudentLocales();
    state.uiLocale = detectInitialLocale();
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
      state.autoJoinToken = token;
      const payload = getJoinData(token);
      state.joinSessionId = payload?.sessionId || "";
      applyJoinTokenState(payload);
      if (payload?.sessionId) {
        // Fetched in the background so it can't delay wiring up the join
        // controls below -- the join screen stays responsive immediately,
        // then narrows to the session's locales once this resolves.
        fetchSessionPublicInfo(payload.sessionId).then((info) => {
          if (!info) return;
          refreshJoinedSessionLabel();
          renderStudentLocales(info.targetLocales);
        });
      }
    }
    applyStudentI18n();

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
        toast(t("msg.loggedOut", "로그아웃되었습니다."));
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
        updateMicUi(false);
        toast("마이크를 잠시 껐습니다.");
      } catch (error) {
        state.micPausedByUser = false;
        updateMicUi(true);
        toast(`마이크를 끄지 못했습니다: ${error.message}`, "error");
      }
    });
    $("mic-resume").addEventListener("click", async () => {
      if (!state.room) return;
      const room = state.room;
      state.micPausedByUser = false;
      try {
        await room.localParticipant.setMicrophoneEnabled(true);
        updateMicUi(true);
        toast("마이크를 다시 켰습니다.");
      } catch (error) {
        state.micPausedByUser = true;
        updateMicUi(false);
        toast(`마이크를 켜지 못했습니다: ${error.message}`, "error");
      }
    });
    const openQr = () => {
      if (typeof $("qr-dialog").showModal === "function") $("qr-dialog").showModal();
      else $("qr-dialog").setAttribute("open", "");
    };
    $("show-qr").addEventListener("click", openQr);
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
