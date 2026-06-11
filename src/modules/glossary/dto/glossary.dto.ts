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

  @ApiProperty({ example: '미토콘드리아' })
  @IsString()
  @MaxLength(200)
  term: string;

  @ApiPropertyOptional({ example: '미토콘드리아' })
  @IsOptional()
  @IsString()
  @MaxLength(200)
  pronunciation?: string;

  @ApiPropertyOptional({ example: '세포의 에너지 공장' })
  @IsOptional()
  @IsString()
  definition?: string;

  @ApiPropertyOptional({
    example: { 'zh-CN': '线粒体', 'vi-VN': 'Ty thể' },
    description: 'locale → 번역어 매핑',
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
