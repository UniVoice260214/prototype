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
import { Session } from '../../session/entities/session.entity';
import { TranscriptTranslationEntry } from '../../events/events.types';

/**
 * 세션 중 확정된 자막 세그먼트 한 건.
 * 워커가 발행한 transcripts.segment 이벤트를 그대로 저장해
 * 수업 후 이력 조회(스크롤백)를 지원한다.
 */
@Entity('transcript_segments')
@Index(['sessionId', 'sequence'])
export class TranscriptSegment {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  sessionId: string;

  @ManyToOne(() => Session, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'sessionId' })
  session: Session;

  /**
   * 워커가 만드는 `{sessionId}-seg-{sequence}` 식별자. 재전송 멱등 처리 키.
   * 워커 재기동 시 sequence 가 1부터 다시 시작하는 알려진 제약이 있어,
   * 같은 segmentId 재수신은 최신 이벤트로 덮어쓴다.
   */
  @Index({ unique: true })
  @Column({ type: 'varchar', length: 120 })
  segmentId: string;

  @Column({ type: 'int' })
  sequence: number;

  /** lexicon 교정이 적용된 한국어 원문 (자막·번역의 단일 출처). */
  @Column({ type: 'text' })
  textKo: string;

  /** 교정 전 STT 원문 (회귀 분석·QA용). */
  @Column({ type: 'text', nullable: true })
  rawTextKo: string | null;

  @Column({ type: 'real', nullable: true })
  sttConfidence: number | null;

  /** locale → { text, isFallback }. 학생에게 실제 전달된 자막 그대로. */
  @Column({ type: 'jsonb', default: () => "'{}'::jsonb" })
  translations: Record<string, TranscriptTranslationEntry>;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
