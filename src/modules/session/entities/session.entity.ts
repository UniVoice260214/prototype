import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  OneToMany,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { Course } from '../../course/entities/course.entity';
import { Material } from '../../material/entities/material.entity';

export type SessionStatus = 'active' | 'ended';

@Entity('sessions')
export class Session {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  courseId: string;

  @ManyToOne(() => Course, (course) => course.sessions, {
    onDelete: 'RESTRICT',
  })
  @JoinColumn({ name: 'courseId' })
  course: Course;

  @Index({ unique: true })
  @Column({ type: 'varchar', length: 200 })
  liveKitRoomName: string;

  @Column({ type: 'enum', enum: ['active', 'ended'], default: 'active' })
  status: SessionStatus;

  /** e.g. ['zh-CN', 'vi-VN', 'mn-MN'] */
  @Column({ type: 'text', array: true, default: () => 'ARRAY[]::text[]' })
  targetLocales: string[];

  @Column({ type: 'timestamptz' })
  startedAt: Date;

  @Column({ type: 'timestamptz', nullable: true })
  endedAt: Date | null;

  @OneToMany(() => Material, (material) => material.session)
  materials: Material[];

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
