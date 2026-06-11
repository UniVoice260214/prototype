import { Injectable, NotFoundException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { Student } from './entities/student.entity';
import { UpdateStudentDto } from './dto/update-student.dto';

@Injectable()
export class StudentService {
  constructor(
    @InjectRepository(Student) private readonly students: Repository<Student>,
  ) {}

  findAll(): Promise<Student[]> {
    return this.students.find();
  }

  async findOne(id: string): Promise<Student> {
    const s = await this.students.findOne({ where: { id } });
    if (!s) throw new NotFoundException(`Student ${id} not found`);
    return s;
  }

  async update(id: string, dto: UpdateStudentDto): Promise<Student> {
    const s = await this.findOne(id);
    Object.assign(s, dto);
    return this.students.save(s);
  }

  async remove(id: string): Promise<void> {
    const res = await this.students.delete(id);
    if (!res.affected) throw new NotFoundException(`Student ${id} not found`);
  }
}
