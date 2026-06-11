/**
 * 엔드투엔드 스모크 테스트 (UTF-8 안전, Node fetch 사용).
 *
 *   npx ts-node src/scripts/smoke.ts
 *
 * 서버가 http://localhost:3000 에 떠 있어야 한다.
 * LiveKit 자격증명이 있으면 세션/QR 단계까지 검증한다.
 */
const BASE = process.env.BASE_URL ?? 'http://localhost:3000';

let passes = 0;
let failures = 0;

function check(name: string, cond: boolean, extra?: unknown) {
  if (cond) {
    passes++;
    console.log(`  ✅ ${name}`);
  } else {
    failures++;
    console.log(`  ❌ ${name}`, extra ?? '');
  }
}

async function req(
  method: string,
  path: string,
  body?: unknown,
  token?: string,
) {
  const headers: Record<string, string> = {};
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json: any = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    /* non-json */
  }
  return { status: res.status, json, text };
}

async function main() {
  console.log(`\n▶ Smoke test against ${BASE}\n`);

  // 1. Admin login
  console.log('1) Auth');
  const login = await req('POST', '/auth/login', {
    email: process.env.SEED_ADMIN_EMAIL ?? 'admin@univoice.local',
    password: process.env.SEED_ADMIN_PASSWORD ?? 'Admin1234!',
  });
  check('admin 로그인 200', login.status === 200, login.text);
  const token = login.json?.accessToken as string;
  check('accessToken 발급', !!token);

  check(
    '인증 없이 보호 엔드포인트 401',
    (await req('GET', '/users')).status === 401,
  );

  // 2. School / Department (한글 UTF-8 라운드트립)
  console.log('2) School / Department (UTF-8)');
  const school = await req('POST', '/schools', { name: '한국대학교' }, token);
  check('학교 생성 201', school.status === 201, school.text);
  check(
    '한글 라운드트립 정확',
    school.json?.name === '한국대학교',
    school.json?.name,
  );
  const schoolId = school.json?.id;

  const dept = await req(
    'POST',
    '/departments',
    { name: '컴퓨터공학과', schoolId },
    token,
  );
  check('학과 생성 201', dept.status === 201, dept.text);
  const departmentId = dept.json?.id;

  // 3. Professor user + profile + course
  console.log('3) User(professor) / Professor / Course');
  const profEmail = `prof_${Date.now()}@univ.ac.kr`;
  const profUser = await req(
    'POST',
    '/users',
    { email: profEmail, password: 'Prof1234!', name: '김교수', role: 'professor' },
    token,
  );
  check('교수 User 생성 201', profUser.status === 201, profUser.text);
  const userId = profUser.json?.id;

  const professor = await req(
    'POST',
    '/professors',
    { userId, departmentId },
    token,
  );
  check('Professor 프로필 생성 201', professor.status === 201, professor.text);
  const professorId = professor.json?.id;

  const course = await req(
    'POST',
    '/courses',
    { name: '인공지능 입문', departmentId, professorId },
    token,
  );
  check('과목 생성 201', course.status === 201, course.text);
  const courseId = course.json?.id;

  // 4. Glossary (jsonb translations + 캐시)
  console.log('4) Glossary (jsonb translations)');
  const glossary = await req(
    'POST',
    '/glossary',
    {
      courseId,
      term: '미토콘드리아',
      pronunciation: '미토콘드리아',
      definition: '세포의 에너지 공장',
      translations: { 'zh-CN': '线粒体', 'vi-VN': 'Ty thể' },
    },
    token,
  );
  check('용어 생성 201', glossary.status === 201, glossary.text);
  check(
    'jsonb translations 저장',
    glossary.json?.translations?.['zh-CN'] === '线粒体',
    glossary.json?.translations,
  );

  // 5. Professor login (역할 분기)
  console.log('5) Professor 로그인');
  const profLogin = await req('POST', '/auth/login', {
    email: profEmail,
    password: 'Prof1234!',
  });
  check('교수 로그인 200', profLogin.status === 200, profLogin.text);
  check('role=professor', profLogin.json?.role === 'professor');

  // 6. Student signup/login
  console.log('6) Student 가입/로그인');
  const studentEmail = `stu_${Date.now()}@univ.ac.kr`;
  const signup = await req('POST', '/auth/student/signup', {
    email: studentEmail,
    password: 'Stud1234!',
    name: 'Nguyen Van A',
    preferredLocale: 'vi-VN',
  });
  check('학생 가입 201', signup.status === 201, signup.text);
  check('학생 토큰 발급', !!signup.json?.accessToken);

  // 7. Session start (LiveKit 필요)
  console.log('7) Session start (LiveKit 자격증명 필요)');
  const session = await req(
    'POST',
    '/sessions/start',
    { courseId, targetLocales: ['zh-CN', 'vi-VN'] },
    profLogin.json?.accessToken,
  );
  if (session.status === 201) {
    check('세션 시작 201', true);
    const sessionId = session.json?.session?.id;
    check('교수 LiveKit token 반환', !!session.json?.liveKit?.token);

    // 8. QR
    console.log('8) QR 생성');
    const qr = await req('GET', `/qr/${sessionId}`, undefined, token);
    check('QR 생성 200', qr.status === 200, qr.text);
    check(
      'QR PNG data URL',
      typeof qr.json?.qrImage === 'string' &&
        qr.json.qrImage.startsWith('data:image/png;base64,'),
    );

    // 9. Student token via session
    console.log('9) 학생 세션 token');
    const stoken = await req('POST', `/sessions/${sessionId}/token`, {
      joinToken: qr.json?.joinToken,
      locale: 'vi-VN',
    });
    check('학생 LiveKit token 200', stoken.status === 201 || stoken.status === 200, stoken.text);
  } else if (session.status === 503) {
    console.log(
      '  ⏭️  세션 시작 SKIP — LiveKit 미설정 (503). .env에 LIVEKIT_* 채우면 검증됩니다.',
    );
  } else {
    check('세션 시작', false, `status=${session.status} ${session.text}`);
  }

  // 10. Material upload (Azurite Blob + indexing 이벤트)
  console.log('10) Material 업로드 (Blob)');
  const pdfBytes = Buffer.from(
    '%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF',
    'utf-8',
  );
  const form = new FormData();
  form.append(
    'file',
    new Blob([pdfBytes], { type: 'application/pdf' }),
    'lecture-week1.pdf',
  );
  form.append('courseId', courseId);
  form.append('sourceType', 'lecture');
  form.append('week', '1');
  const upRes = await fetch(`${BASE}/materials/upload`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  const upText = await upRes.text();
  let upJson: any = null;
  try {
    upJson = JSON.parse(upText);
  } catch {
    /* */
  }
  if (upRes.status === 503) {
    console.log('  ⏭️  업로드 SKIP — Azurite 미실행(503).');
  } else {
    check('자료 업로드 201', upRes.status === 201, upText);
    check('blobUrl 반환', typeof upJson?.blobUrl === 'string', upJson?.blobUrl);
    check('indexingStatus=pending', upJson?.indexingStatus === 'pending');
  }

  console.log(`\n── 결과: ✅ ${passes} 통과 / ❌ ${failures} 실패 ──\n`);
  process.exit(failures > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Smoke test crashed:', err);
  process.exit(1);
});
