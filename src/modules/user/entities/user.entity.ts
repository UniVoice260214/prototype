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

  /** Hidden from serialized API responses. */
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
