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
 * Locale string to translated term mapping.
 */
export type GlossaryTranslations = Record<string, string>;

@Entity('glossaries')
@Index(['courseId', 'term'], { unique: true })
export class Glossary {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  courseId: string;

  @ManyToOne(() => Course, (course) => course.glossaries, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'courseId' })
  course: Course;

  /** Source term in Korean. */
  @Column({ type: 'varchar', length: 200 })
  term: string;

  /** Pronunciation text for STT phrase lists or TTS lexicons. */
  @Column({ type: 'varchar', length: 200, nullable: true })
  pronunciation: string | null;

  @Column({ type: 'text', nullable: true })
  definition: string | null;

  /** Mapping from locale key to translated term. */
  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  translations: GlossaryTranslations;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
