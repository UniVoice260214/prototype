import { ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsInt, IsOptional, IsString, Max, Min } from 'class-validator';

export const TRANSCRIPT_DEFAULT_LIMIT = 200;
export const TRANSCRIPT_MAX_LIMIT = 500;

export class ListTranscriptsQueryDto {
  @ApiPropertyOptional({
    description:
      'Return only segments with sequence greater than this value (for incremental polling)',
  })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(0)
  afterSequence?: number;

  @ApiPropertyOptional({
    default: TRANSCRIPT_DEFAULT_LIMIT,
    maximum: TRANSCRIPT_MAX_LIMIT,
  })
  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(TRANSCRIPT_MAX_LIMIT)
  limit?: number;
}

export class StudentTranscriptQueryDto extends ListTranscriptsQueryDto {
  @ApiPropertyOptional({
    description:
      'Join token issued from the QR flow. Optional when a Student JWT is used.',
  })
  @IsOptional()
  @IsString()
  joinToken?: string;
}
