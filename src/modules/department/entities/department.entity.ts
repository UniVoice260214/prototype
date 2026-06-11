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
import { School } from '../../school/entities/school.entity';
import { Course } from '../../course/entities/course.entity';
import { Professor } from '../../professor/entities/professor.entity';

@Entity('departments')
export class Department {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 200 })
  name: string;

  @Column({ type: 'uuid' })
  schoolId: string;

  @ManyToOne(() => School, (school) => school.departments, {
    onDelete: 'RESTRICT',
  })
  @JoinColumn({ name: 'schoolId' })
  school: School;

  @OneToMany(() => Course, (course) => course.department)
  courses: Course[];

  @OneToMany(() => Professor, (professor) => professor.department)
  professors: Professor[];

  @CreateDateColumn()
  createdAt: Date;

  @UpdateDateColumn()
  updatedAt: Date;
}
