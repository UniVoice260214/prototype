import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { IsEnum, IsInt, IsOptional, IsUUID, Min } from 'class-validator';
import { Transform } from 'class-transformer';

export class UploadMaterialDto {
  @ApiProperty({ format: 'uuid' })
  @IsUUID()
  courseId: string;

  @ApiPropertyOptional({ format: 'uuid' })
  @IsOptional()
  @IsUUID()
  sessionId?: string;

  @ApiProperty({ enum: ['lecture', 'major'] })
  @IsEnum(['lecture', 'major'])
  sourceType: 'lecture' | 'major';

  @ApiPropertyOptional({ example: 3 })
  @IsOptional()
  @Transform(({ value }) => (value != null ? parseInt(value, 10) : undefined))
  @IsInt()
  @Min(1)
  week?: number;
}
