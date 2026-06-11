import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { Course } from '../../course/entities/course.entity';

/**
 * locale string -> translated term. e.g. { 'zh-CN': '线粒体', 'vi-VN': 'Ty thể' }
 */
export type GlossaryTranslations = Record<string, string>;

@Entity('glossaries')
@Index(['courseId', 'term'], { unique: true })
export class Glossary {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  courseId: string;

  @ManyToOne(() => Course, (course) => course.glossaries, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'courseId' })
  course: Course;

  /** 한국어 원문 용어 */
  @Column({ type: 'varchar', length: 200 })
  term: string;

  /** IPA or 한글 발음 표기. STT phrase list / TTS lexicon에 활용. */
  @Column({ type: 'varchar', length: 200, nullable: true })
  pronunciation: string | null;

  @Column({ type: 'text', nullable: true })
  definition: string | null;

  /** locale 키 → 번역어 매핑 */
  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  translations: GlossaryTranslations;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
