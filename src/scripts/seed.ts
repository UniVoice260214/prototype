/**
 * Seed script for creating the first admin user.
 *
 *   npm run seed
 *
 * If the admin email already exists, the script exits without overwriting it.
 */
import 'reflect-metadata';
import * as bcrypt from 'bcrypt';
import { dataSource } from '../config/typeorm.datasource';
import { User } from '../modules/user/entities/user.entity';

const SEED_ADMIN = {
  email: process.env.SEED_ADMIN_EMAIL ?? 'admin@univoice.local',
  password: process.env.SEED_ADMIN_PASSWORD ?? 'Admin1234!',
  name: process.env.SEED_ADMIN_NAME ?? 'Root Admin',
};

async function main() {
  await dataSource.initialize();
  const repo = dataSource.getRepository(User);

  const existing = await repo.findOne({ where: { email: SEED_ADMIN.email } });
  if (existing) {
    console.log(`Admin already exists: ${existing.email} (id=${existing.id})`);
    await dataSource.destroy();
    return;
  }

  const passwordHash = await bcrypt.hash(SEED_ADMIN.password, 10);
  const user = await repo.save(
    repo.create({
      email: SEED_ADMIN.email,
      passwordHash,
      name: SEED_ADMIN.name,
      role: 'admin',
    }),
  );
  console.log('Seeded admin user:');
  console.log(`   id:       ${user.id}`);
  console.log(`   email:    ${user.email}`);
  console.log(`   password: ${SEED_ADMIN.password}`);
  console.log('\nLogin via: POST /auth/login { email, password }');
  await dataSource.destroy();
}

main().catch((err) => {
  console.error('Seed failed:', err);
  process.exit(1);
});
