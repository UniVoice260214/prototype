import { readFile } from 'node:fs/promises';
import process from 'node:process';
import { parse } from 'dotenv';

const path = process.argv[2] || '.env.staging';
const placeholderPattern = /replace[_-]?with|example\.com|your[-_]/i;
const errors = [];

let values;
try {
  values = parse(await readFile(path));
} catch (error) {
  console.error(`Cannot read ${path}: ${error.message}`);
  process.exit(1);
}

function requireValue(name, { minLength = 1, pattern } = {}) {
  const value = values[name]?.trim() || '';
  if (!value) {
    errors.push(`${name} is required`);
    return '';
  }
  if (placeholderPattern.test(value)) {
    errors.push(`${name} still contains an example or placeholder value`);
  }
  if (value.length < minLength) {
    errors.push(`${name} must contain at least ${minLength} characters`);
  }
  if (pattern && !pattern.test(value)) {
    errors.push(`${name} has an invalid format`);
  }
  return value;
}

const domain = requireValue('STAGING_DOMAIN', {
  pattern: /^(?!https?:\/\/)[a-z0-9.-]+\.[a-z]{2,}$/i,
});
requireValue('ACME_EMAIL', { pattern: /^[^@\s]+@[^@\s]+\.[^@\s]+$/ });
requireValue('POSTGRES_PASSWORD', {
  minLength: 24,
  pattern: /^[A-Za-z0-9_-]+$/,
});
requireValue('REDIS_PASSWORD', {
  minLength: 24,
  pattern: /^[A-Za-z0-9_-]+$/,
});
requireValue('JWT_SECRET', { minLength: 32 });
requireValue('SEED_ADMIN_EMAIL', {
  pattern: /^[^@\s]+@[^@\s]+\.[^@\s]+$/,
});
requireValue('SEED_ADMIN_PASSWORD', { minLength: 12 });
requireValue('LIVEKIT_URL', { pattern: /^wss:\/\/.+/i });
requireValue('LIVEKIT_API_KEY');
requireValue('LIVEKIT_API_SECRET');
requireValue('AZURE_SPEECH_KEY');
requireValue('AZURE_SPEECH_REGION');
requireValue('AZURE_BLOB_CONNECTION_STRING');

const provider = requireValue('TRANSLATE_PROVIDER');
if (provider === 'openai') {
  requireValue('OPENAI_API_KEY');
} else if (provider === 'azure') {
  requireValue('AZURE_OPENAI_ENDPOINT', { pattern: /^https:\/\/.+/i });
  requireValue('AZURE_OPENAI_API_KEY');
  requireValue('AZURE_OPENAI_DEPLOYMENT');
} else if (provider) {
  errors.push('TRANSLATE_PROVIDER must be openai or azure');
}

if (domain && domain === values.LIVEKIT_URL) {
  errors.push('STAGING_DOMAIN and LIVEKIT_URL must not be identical');
}

if (errors.length > 0) {
  console.error(`Staging environment validation failed (${errors.length}):`);
  for (const error of errors) console.error(`- ${error}`);
  process.exit(1);
}

console.log(`Staging environment is valid for https://${domain}`);
