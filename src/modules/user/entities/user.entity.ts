import { Exclude } from 'class-transformer';
import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  OneToOne,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { Professor } from '../../professor/entities/professor.entity';

export type UserRole = 'admin' | 'professor';

@Entity('users')
export class User {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Index({ unique: true })
  @Column({ type: 'varchar', length: 255 })
  email: string;

  /** 응답 직렬화에서 제외 (ClassSerializerInterceptor). bcrypt 비교용 내부 접근은 영향 없음. */
  @Exclude()
  @Column({ type: 'varchar', length: 255 })
  passwordHash: string;

  @Column({ type: 'varchar', length: 100 })
  name: string;

  @Column({ type: 'enum', enum: ['admin', 'professor'] })
  role: UserRole;

  @OneToOne(() => Professor, (professor) => professor.user)
  professor?: Professor;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
