export const SUPPORTED_TARGET_LOCALES = [
  'zh-CN',
  'zh-TW',
  'vi-VN',
  'mn-MN',
  'en-US',
  'ja-JP',
  'uk-UA',
] as const;

export type SupportedTargetLocale = (typeof SUPPORTED_TARGET_LOCALES)[number];
