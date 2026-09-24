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
import { Student } from '../../student/entities/student.entity';
import { Session } from './session.entity';

/**
 * 학생의 세션 참여 기록.
 *
 * 용도:
 *  1. 지난 수업 자막 열람 권한 — Student JWT 만으로는 아무 세션이나 조회할 수
 *     있었던 구멍을 막고, 실제 참여한 세션만 허용한다.
 *  2. 학생용 "내 수업 목록" (GET /students/me/sessions).
 *
 * 한계: QR 게스트 입장은 studentId 가 없어 기록되지 않는다 — 게스트는
 * joinToken 유효기간(24h) 내에만 해당 세션 자막을 다시 볼 수 있다.
 */
@Entity('session_attendances')
@Index(['studentId', 'sessionId'], { unique: true })
export class SessionAttendance {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  studentId: string;

  @ManyToOne(() => Student, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'studentId' })
  student: Student;

  @Column({ type: 'uuid' })
  sessionId: string;

  @ManyToOne(() => Session, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'sessionId' })
  session: Session;

  /** 입장 시 선택한 번역 언어. 재입장 시 최신 값으로 갱신된다. */
  @Column({ type: 'varchar', length: 16 })
  locale: string;

  @Column({ type: 'timestamptz' })
  joinedAt: Date;

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
