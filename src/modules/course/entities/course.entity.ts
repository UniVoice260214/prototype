import {
  Column,
  CreateDateColumn,
  Entity,
  JoinColumn,
  ManyToOne,
  OneToMany,
  PrimaryGeneratedColumn,
  UpdateDateColumn,
} from 'typeorm';
import { Department } from '../../department/entities/department.entity';
import { Professor } from '../../professor/entities/professor.entity';
import { Session } from '../../session/entities/session.entity';
import { Material } from '../../material/entities/material.entity';
import { Glossary } from '../../glossary/entities/glossary.entity';

/** AI 워커·RAG 서비스가 인식하는 전공 키 (rag-experiment MAJOR_ROUTERS 와 동일). */
export const COURSE_MAJORS = ['ai', 'hss', 'bme'] as const;
export type CourseMajor = (typeof COURSE_MAJORS)[number];

@Entity('courses')
export class Course {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 200 })
  name: string;

  /**
   * 과목의 전공. 수업 시작 시 워커로 전달되어 그 전공의 RAG 인덱스만 검색하고
   * STT 전공 용어 교정(lexicon)을 켠다. null 이면 워커 설정(RAG_DEFAULT_MAJOR)으로 폴백.
   */
  @Column({ type: 'varchar', length: 16, nullable: true })
  major: CourseMajor | null;

  @Column({ type: 'uuid' })
  departmentId: string;

  @ManyToOne(() => Department, (department) => department.courses, {
    onDelete: 'RESTRICT',
  })
  @JoinColumn({ name: 'departmentId' })
  department: Department;

  @Column({ type: 'uuid' })
  professorId: string;

  @ManyToOne(() => Professor, (professor) => professor.courses, {
    onDelete: 'RESTRICT',
  })
  @JoinColumn({ name: 'professorId' })
  professor: Professor;

  @OneToMany(() => Session, (session) => session.course)
  sessions: Session[];

  @OneToMany(() => Material, (material) => material.course)
  materials: Material[];

  @OneToMany(() => Glossary, (glossary) => glossary.course)
  glossaries: Glossary[];

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
