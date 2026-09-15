import { decodeMultipartFilename } from './multipart-filename';

describe('decodeMultipartFilename', () => {
  it('restores UTF-8 filenames that busboy read as latin1', () => {
    const mangled = Buffer.from('3주차 강의안.pptx', 'utf8').toString('latin1');
    expect(decodeMultipartFilename(mangled)).toBe('3주차 강의안.pptx');
  });

  it('leaves ASCII and already-correct names untouched', () => {
    expect(decodeMultipartFilename('I2A_Lecture03.pdf')).toBe(
      'I2A_Lecture03.pdf',
    );
    expect(decodeMultipartFilename('3주차 강의안.pptx')).toBe(
      '3주차 강의안.pptx',
    );
  });

  it('keeps genuine latin1 names that are not valid UTF-8', () => {
    expect(decodeMultipartFilename('résumé.pdf')).toBe('résumé.pdf');
  });
});
