import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsObject,
  IsOptional,
  IsString,
  IsUUID,
  MaxLength,
} from 'class-validator';

export class CreateGlossaryDto {
  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  courseId: string;

  @ApiProperty({ example: 'mitochondria' })
  @IsString()
  @MaxLength(200)
  term: string;

  @ApiPropertyOptional({ example: 'my-toe-kon-dree-uh' })
  @IsOptional()
  @IsString()
  @MaxLength(200)
  pronunciation?: string;

  @ApiPropertyOptional({ example: 'cell energy factory' })
  @IsOptional()
  @IsString()
  definition?: string;

  @ApiPropertyOptional({
    example: { 'zh-CN': 'xianliti', 'vi-VN': 'ty-the' },
    description: 'Mapping from locale to translated term',
  })
  @IsOptional()
  @IsObject()
  translations?: Record<string, string>;
}

export class UpdateGlossaryDto {
  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(200)
  term?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  @MaxLength(200)
  pronunciation?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsString()
  definition?: string;

  @ApiPropertyOptional()
  @IsOptional()
  @IsObject()
  translations?: Record<string, string>;
}
