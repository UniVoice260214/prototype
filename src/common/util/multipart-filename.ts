/**
 * 브라우저는 multipart filename 을 UTF-8 로 보내지만 multer(busboy) 는 latin1 로
 * 읽어 한글이 깨진 채("½Ç½Ã°£ …") 저장된다. 바이트를 UTF-8 로 되돌리되,
 * 이미 올바른 문자열(ASCII 등)은 그대로 둔다.
 */
export function decodeMultipartFilename(name: string): string {
  // latin1 로 잘못 읽힌 문자열은 모든 code point 가 0xFF 이하다.
  if (!isLatin1(name)) return name;
  const decoded = Buffer.from(name, 'latin1').toString('utf8');
  // 되돌린 결과에 대체 문자(U+FFFD)가 있으면 원래부터 latin1 이었던 것이다.
  return decoded.includes('�') ? name : decoded;
}

function isLatin1(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    if (value.charCodeAt(i) > 0xff) return false;
  }
  return true;
}
