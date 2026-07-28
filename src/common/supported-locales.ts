export const SUPPORTED_TARGET_LOCALES = [
  'zh-CN',
  'vi-VN',
  'mn-MN',
  'en-US',
  'ja-JP',
] as const;

export type SupportedTargetLocale = (typeof SUPPORTED_TARGET_LOCALES)[number];
