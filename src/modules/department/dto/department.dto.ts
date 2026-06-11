import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsOptional, IsString, IsUUID, MaxLength } from 'class-validator';

export class CreateDepartmentDto {
  @ApiProperty({ example: '컴퓨터공학과' })
  @IsString()
  @MaxLength(200)
  name: string;

  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  schoolId: string;
}

export class UpdateDepartmentDto {
  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(200)
  name?: string;
}
