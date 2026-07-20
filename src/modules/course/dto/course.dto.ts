import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsOptional, IsString, IsUUID, MaxLength } from 'class-validator';

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
}
