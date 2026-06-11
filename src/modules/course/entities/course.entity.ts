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

@Entity('courses')
export class Course {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 200 })
  name: string;

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
