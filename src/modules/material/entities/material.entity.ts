import {
  Column,
  CreateDateColumn,
  Entity,
  JoinColumn,
  ManyToOne,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { Course } from '../../course/entities/course.entity';
import { Session } from '../../session/entities/session.entity';

export type MaterialSourceType = 'lecture' | 'major';
export type IndexingStatus = 'pending' | 'processing' | 'done' | 'failed';

@Entity('materials')
export class Material {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  /** 사전 업로드 시 nullable. 세션 종료 후 분석 시 채워질 수 있음. */
  @Column({ type: 'uuid', nullable: true })
  sessionId: string | null;

  @ManyToOne(() => Session, (session) => session.materials, {
    onDelete: 'SET NULL',
    nullable: true,
  })
  @JoinColumn({ name: 'sessionId' })
  session: Session | null;

  @Column({ type: 'uuid' })
  courseId: string;

  @ManyToOne(() => Course, (course) => course.materials, { onDelete: 'RESTRICT' })
  @JoinColumn({ name: 'courseId' })
  course: Course;

  @Column({ type: 'text' })
  blobUrl: string;

  @Column({ type: 'varchar', length: 500 })
  originalFilename: string;

  @Column({ type: 'enum', enum: ['lecture', 'major'] })
  sourceType: MaterialSourceType;

  @Column({ type: 'int', nullable: true })
  week: number | null;

  @Column({
    type: 'enum',
    enum: ['pending', 'processing', 'done', 'failed'],
    default: 'pending',
  })
  indexingStatus: IndexingStatus;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
