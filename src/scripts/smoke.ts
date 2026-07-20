/**
 * Basic smoke test for the API.
 *
 * Run with:
 *   npx ts-node src/scripts/smoke.ts
 *
 * Assumes the server is already running at BASE_URL.
 */
const BASE = process.env.BASE_URL ?? 'http://localhost:3000';

let passes = 0;
let failures = 0;

function check(name: string, cond: boolean, extra?: unknown) {
  if (cond) {
    passes++;
    console.log(`  OK ${name}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}`, extra ?? '');
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
  console.log(`\nSmoke test against ${BASE}\n`);

  // 1. Admin login
  console.log('1) Auth');
  const login = await req('POST', '/auth/login', {
    email: process.env.SEED_ADMIN_EMAIL ?? 'admin@univoice.local',
    password: process.env.SEED_ADMIN_PASSWORD ?? 'Admin1234!',
  });
  check('admin login returns 200', login.status === 200, login.text);
  const token = login.json?.accessToken as string;
  check('access token returned', !!token);

  check(
    'protected endpoint returns 401 without auth',
    (await req('GET', '/users')).status === 401,
  );

  // 2. School / Department
  console.log('2) School / Department');
  const school = await req('POST', '/schools', { name: 'Global University' }, token);
  check('school created', school.status === 201, school.text);
  check(
    'school name persisted',
    school.json?.name === 'Global University',
    school.json?.name,
  );
  const schoolId = school.json?.id;

  const dept = await req(
    'POST',
    '/departments',
    { name: 'Computer Science', schoolId },
    token,
  );
  check('department created', dept.status === 201, dept.text);
  const departmentId = dept.json?.id;

  // 3. Professor user + profile + course
  console.log('3) User(professor) / Professor / Course');
  const profEmail = `prof_${Date.now()}@univ.ac.kr`;
  const profUser = await req(
    'POST',
    '/users',
    {
      email: profEmail,
      password: 'Prof1234!',
      name: 'Professor Kim',
      role: 'professor',
    },
    token,
  );
  check('professor user created', profUser.status === 201, profUser.text);
  const userId = profUser.json?.id;

  const professor = await req(
    'POST',
    '/professors',
    { userId, departmentId },
    token,
  );
  check('professor profile created', professor.status === 201, professor.text);
  const professorId = professor.json?.id;

  const course = await req(
    'POST',
    '/courses',
    { name: 'Intro to AI', departmentId, professorId },
    token,
  );
  check('course created', course.status === 201, course.text);
  const courseId = course.json?.id;

  // 4. Glossary
  console.log('4) Glossary');
  const glossary = await req(
    'POST',
    '/glossary',
    {
      courseId,
      term: 'mitochondria',
      pronunciation: 'my-toe-kon-dree-uh',
      definition: 'cell energy factory',
      translations: { 'zh-CN': 'xianliti', 'vi-VN': 'ty-the' },
    },
    token,
  );
  check('glossary created', glossary.status === 201, glossary.text);
  check(
    'jsonb translations stored',
    glossary.json?.translations?.['zh-CN'] === 'xianliti',
    glossary.json?.translations,
  );

  // 5. Professor login
  console.log('5) Professor login');
  const profLogin = await req('POST', '/auth/login', {
    email: profEmail,
    password: 'Prof1234!',
  });
  check('professor login returns 200', profLogin.status === 200, profLogin.text);
  check('role=professor', profLogin.json?.role === 'professor');

  // 6. Student signup/login
  console.log('6) Student signup/login');
  const studentEmail = `stu_${Date.now()}@univ.ac.kr`;
  const signup = await req('POST', '/auth/student/signup', {
    email: studentEmail,
    password: 'Stud1234!',
    name: 'Nguyen Van A',
    preferredLocale: 'vi-VN',
  });
  check('student signup created account', signup.status === 201, signup.text);
  check('student token returned', !!signup.json?.accessToken);

  // 7. Session start (requires LiveKit config)
  console.log('7) Session start');
  const session = await req(
    'POST',
    '/sessions/start',
    { courseId, targetLocales: ['zh-CN', 'vi-VN'] },
    profLogin.json?.accessToken,
  );
  if (session.status === 201) {
    check('session started', true);
    const sessionId = session.json?.session?.id;
    check('professor LiveKit token returned', !!session.json?.liveKit?.token);

    // 8. QR
    console.log('8) QR');
    const qr = await req('GET', `/qr/${sessionId}`, undefined, token);
    check('qr generated', qr.status === 200, qr.text);
    check(
      'qr image is a PNG data URL',
      typeof qr.json?.qrImage === 'string' &&
        qr.json.qrImage.startsWith('data:image/png;base64,'),
    );

    // 9. Student token via session
    console.log('9) Student session token');
    const stoken = await req('POST', `/sessions/${sessionId}/token`, {
      joinToken: qr.json?.joinToken,
      locale: 'vi-VN',
    });
    check(
      'student LiveKit token returned',
      stoken.status === 201 || stoken.status === 200,
      stoken.text,
    );
  } else if (session.status === 503) {
    console.log(
      '  WARN session start skipped because LiveKit is not configured (503).',
    );
  } else {
    check('session start', false, `status=${session.status} ${session.text}`);
  }

  // 10. Material upload (requires Blob config)
  console.log('10) Material upload');
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
    console.log('  WARN upload skipped because Blob storage is not configured (503).');
  } else {
    check('material uploaded', upRes.status === 201, upText);
    check('blobUrl returned', typeof upJson?.blobUrl === 'string', upJson?.blobUrl);
    check('indexingStatus=pending', upJson?.indexingStatus === 'pending');
  }

  console.log(`\nResult: ${passes} passed / ${failures} failed\n`);
  process.exit(failures > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error('Smoke test crashed:', err);
  process.exit(1);
});
