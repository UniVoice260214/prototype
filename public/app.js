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
    currentAudioTrack: null,
  };

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

  // locale-dialog lives outside #student-app (top-level, like qr-dialog does
  // for the professor side) so showModal() never fights a hidden ancestor.
  const STUDENT_I18N_SCOPE = "#student-app [data-i18n], #locale-dialog [data-i18n]";
  const STUDENT_I18N_PLACEHOLDER_SCOPE = "#student-app [data-i18n-placeholder], #locale-dialog [data-i18n-placeholder]";

  function applyStudentI18n() {
    document.querySelectorAll(STUDENT_I18N_SCOPE).forEach((el) => {
      const value = translate(el.dataset.i18n);
      if (value != null) el.textContent = value;
    });
    document.querySelectorAll(STUDENT_I18N_PLACEHOLDER_SCOPE).forEach((el) => {
      const value = translate(el.dataset.i18nPlaceholder);
      if (value != null) el.setAttribute("placeholder", value);
    });
    const toggle = $("toggle-captions-size");
    if (toggle) {
      const enlarged = $("captions").classList.contains("captions-large");
      toggle.textContent = "Aa";
      toggle.setAttribute("aria-label", t(enlarged ? "captions.shrink" : "captions.enlarge", enlarged ? "자막 기본 크기" : "자막 크게 보기"));
    }
    refreshJoinedSessionLabel();
    refreshTokenStatus();
  }

  // These two show composed text (course name, error state) that a generic
  // data-i18n text swap can't represent, so they own their own re-render
  // and get called explicitly instead of relying on the [data-i18n] pass.
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

  function refreshTokenStatus() {
    const statusText = $("token-status-text");
    const statusIcon = $("token-status-icon");
    if (!state.autoJoinToken) {
      statusText.textContent = t("token.empty", "QR을 스캔하면 자동으로 연결됩니다.");
      statusIcon.textContent = "○";
      statusIcon.classList.remove("token-status-icon--error");
      return;
    }
    if (state.joinTokenInvalid) {
      statusText.textContent = t("token.invalid", "입장 정보를 확인할 수 없습니다. QR을 다시 스캔해주세요.");
      statusIcon.textContent = "!";
      statusIcon.classList.add("token-status-icon--error");
      return;
    }
    statusText.textContent = t("token.auto", "QR 링크로 자동 연결됨");
    statusIcon.textContent = "✓";
    statusIcon.classList.remove("token-status-icon--error");
  }

  function setUiLocale(code) {
    state.uiLocale = code;
    applyStudentI18n();
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
        $("selected-language").textContent = `${locale.flag} ${localeLabel(locale)}`;
        setUiLocale(locale.code);
      });
    });
  }

  function renderLocaleDialogOptions() {
    const allowed = state.sessionPublicInfo?.targetLocales?.length
      ? LOCALES.filter((locale) => state.sessionPublicInfo.targetLocales.includes(locale.code))
      : LOCALES;
    $("locale-dialog-options").innerHTML = allowed.map((locale) => `
      <label class="locale-option">
        <input type="radio" name="live-locale" value="${locale.code}" ${locale.code === state.selectedStudentLocale ? "checked" : ""}>
        <span><b>${locale.flag}</b><span>${localeLabel(locale)}</span></span>
      </label>
    `).join("");
    document.querySelectorAll('input[name="live-locale"]').forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) changeStudentLocale(input.value);
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
    const manual = $("join-token-input").value.trim();
    return manual || state.autoJoinToken;
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
    $("mic-message").textContent = shouldEnable ? "ON" : "PAUSED";
  }

  async function connectProfessor(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({
      adaptiveStream: true,
      dynacast: true,
    });
    state.room = room;
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
      if (state.room !== room) return;
      clearTimeout(state.connectionStatusTimer);
      $("session-status").innerHTML = "<i></i> 재연결 중";
    });
    room.on(LivekitClient.RoomEvent.Reconnected, async () => {
      if (state.room !== room) return;
      $("session-status").innerHTML = "<i></i> 다시 연결됨";
      try {
        await syncProfessorMicrophone(room);
      } catch (error) {
        toast(`마이크 상태를 복구하지 못했습니다: ${error.message}`, "error");
      }
      state.connectionStatusTimer = setTimeout(() => {
        if (state.room === room) {
          $("session-status").innerHTML = "<i></i> 수업 진행 중";
        }
      }, 2000);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      if (state.room !== room) return;
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
    setModeSwitchVisible(false);
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
    refreshTokenStatus();
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

  async function connectStudent(liveKit) {
    ensureLiveKit();
    const room = new LivekitClient.Room({ adaptiveStream: true });
    state.room = room;
    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication) => {
      if (track.kind !== LivekitClient.Track.Kind.Audio || publication.trackName !== `tts.${state.selectedStudentLocale}`) return;
      attachAudioTrack(track);
    });
    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
      track.detach();
      $("audio-status").textContent = t("live.audioNextWaiting", "다음 번역 음성을 기다리는 중");
    });
    room.on(LivekitClient.RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      handleStudentData(payload, topic);
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      $("audio-status").textContent = t("live.audioDisconnected", "연결이 종료되었습니다");
      toast(t("msg.roomClosed", "강의실 연결이 종료되었습니다."));
    });
    await room.connect(liveKit.liveKitUrl, liveKit.token);
  }

  function attachAudioTrack(track) {
    const audio = $("translation-audio");
    if (state.currentAudioTrack && state.currentAudioTrack !== track) {
      state.currentAudioTrack.detach(audio);
    }
    state.currentAudioTrack = track;
    track.attach(audio);
    audio.play().catch(() => toast(t("msg.autoplayBlocked", "화면을 한 번 눌러 음성 재생을 허용해주세요.")));
    $("audio-status").textContent = t("live.audioPlaying", "번역 음성 재생 중");
  }

  // Finds a track LiveKit already auto-subscribed to (for a locale the user
  // wasn't listening to) and attaches it -- used when switching languages
  // mid-session, since re-subscription events won't fire again for tracks
  // we're already subscribed to.
  function attachExistingTrackForLocale(locale) {
    if (!state.room) return false;
    for (const participant of state.room.remoteParticipants.values()) {
      for (const publication of participant.trackPublications.values()) {
        if (publication.trackName === `tts.${locale}` && publication.track) {
          attachAudioTrack(publication.track);
          return true;
        }
      }
    }
    return false;
  }

  function changeStudentLocale(newLocale) {
    if (newLocale === state.selectedStudentLocale) {
      if ($("locale-dialog").open) $("locale-dialog").close();
      return;
    }
    if (state.sessionPublicInfo?.targetLocales?.length && !state.sessionPublicInfo.targetLocales.includes(newLocale)) {
      toast(t("err.localeNotAvailable", "이 수업에서는 선택하신 언어를 제공하지 않습니다."), "error");
      return;
    }
    state.selectedStudentLocale = newLocale;
    setUiLocale(newLocale);
    updateStudentLocaleLabel();
    $("captions").innerHTML = `<div class="caption-empty" id="captions-empty" data-i18n="live.captionEmpty">${t("live.captionEmpty", "교수님의 발화를 기다리고 있습니다.")}</div>`;
    if (!attachExistingTrackForLocale(newLocale)) {
      $("audio-status").textContent = t("live.audioQueued", "번역 음성 준비 중");
    }
    toast(t("msg.localeChanged", "번역 언어를 변경했습니다."));
    if ($("locale-dialog").open) $("locale-dialog").close();
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
        queued: t("live.audioQueued", "번역 음성 준비 중"),
        playing: t("live.audioPlaying", "번역 음성 재생 중"),
        completed: t("live.audioCompleted", "다음 발화를 기다리는 중"),
        failed: t("live.audioFailed", "음성 생성에 실패했습니다"),
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
    await disconnectRoom();
    state.currentAudioTrack = null;
    $("student-live").classList.add("hidden");
    $("student-join").classList.remove("hidden");
    setModeSwitchVisible(true);
    $("captions").innerHTML = `<div class="caption-empty" id="captions-empty" data-i18n="live.captionEmpty">${t("live.captionEmpty", "교수님의 발화를 기다리고 있습니다.")}</div>`;
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
    $("course-select").addEventListener("change", updateRecoveryControls);
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
      $("token-manual").open = true;
      $("join-token-input").focus();
      $("join-token-input").scrollIntoView({ behavior: "smooth", block: "center" });
    });
    $("copy-link").addEventListener("click", async () => {
      if (!state.joinUrl) return;
      await navigator.clipboard.writeText(state.joinUrl);
      toast("입장 링크를 복사했습니다.");
    });
    $("change-locale").addEventListener("click", () => {
      renderLocaleDialogOptions();
      const dialog = $("locale-dialog");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    });
    $("close-locale-dialog").addEventListener("click", () => $("locale-dialog").close());
    $("toggle-captions-size").addEventListener("click", () => {
      const captions = $("captions");
      const enlarged = captions.classList.toggle("captions-large");
      $("toggle-captions-size").setAttribute("aria-pressed", String(enlarged));
      $("toggle-captions-size").setAttribute("aria-label", t(enlarged ? "captions.shrink" : "captions.enlarge", enlarged ? "자막 기본 크기" : "자막 크게 보기"));
    });
    window.addEventListener("beforeunload", () => {
      clearSessionTimers();
      if (state.room) {
        const room = state.room;
        state.room = null;
        room.disconnect();
      }
    });

    if (state.accessToken && state.mode === "professor") {
      initializeProfessor().catch(() => logout());
    }
  }

  initialize();
})();
