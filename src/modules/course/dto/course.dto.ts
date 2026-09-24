import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsIn, IsOptional, IsString, IsUUID, MaxLength } from 'class-validator';
import { COURSE_MAJORS, CourseMajor } from '../entities/course.entity';

const MAJOR_DESCRIPTION =
  '과목 전공 (ai | hss | bme). 지정하면 수업 중 이 전공의 RAG 인덱스만 검색하고 STT 전공 용어 교정이 켜진다.';

export class CreateCourseDto {
  @ApiProperty({ example: 'Introduction to AI' })
  @IsString()
  @MaxLength(200)
  name: string;

  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  departmentId: string;

  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  professorId: string;

  @ApiPropertyOptional({ enum: COURSE_MAJORS, description: MAJOR_DESCRIPTION })
  @IsOptional()
  @IsIn([...COURSE_MAJORS])
  major?: CourseMajor;
}

export class UpdateCourseDto {
  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(200)
  name?: string;

  @ApiPropertyOptional({ format: 'uuid' })
  @IsOptional()
  @IsUUID()
  professorId?: string;

  @ApiPropertyOptional({ enum: COURSE_MAJORS, description: MAJOR_DESCRIPTION })
  @IsOptional()
  @IsIn([...COURSE_MAJORS])
  major?: CourseMajor;
}
